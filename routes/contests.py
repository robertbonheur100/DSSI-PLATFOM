# routes/contests.py
# ──────────────────────────────────────────────────────────────
#  CONTEST SYSTEM — join, predict, auto-score
# ──────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

contests_bp = Blueprint('contests', __name__)

ENTRY_FEE = 5.00   # USDT


def _db():
    return get_admin_supabase()


def _q(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[Contests query error] {e}")
        return []


def _now():
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# LIST ACTIVE CONTESTS
# ─────────────────────────────────────────────
@contests_bp.route('/')
@login_required
def index():
    db  = _db()
    uid = session['user_id']

    contests = _q(lambda: db.table('football_contests')
                  .select('*').order('created_at', desc=True).execute())

    # Which ones has this user already joined?
    entries = _q(lambda: db.table('contest_entries')
                 .select('contest_id').eq('user_id', uid).execute())
    joined_ids = {e['contest_id'] for e in entries}

    return render_template('football/contests.html',
        contests=contests,
        joined_ids=joined_ids,
    )


# ─────────────────────────────────────────────
# JOIN A CONTEST (pay 5 USDT entry fee)
# ─────────────────────────────────────────────
@contests_bp.route('/join/<contest_id>', methods=['POST'])
@login_required
def join(contest_id):
    db  = _db()
    uid = session['user_id']
    now = _now()

    # Load contest
    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    if not contest_rows:
        flash('Contest not found.', 'error')
        return redirect(url_for('contests.index'))

    contest = contest_rows[0]

    if contest.get('status') != 'active':
        flash('This contest is not active.', 'error')
        return redirect(url_for('contests.index'))

    # Already joined?
    existing = _q(lambda: db.table('contest_entries')
                  .select('id').eq('contest_id', contest_id).eq('user_id', uid).execute())
    if existing:
        flash('You already joined this contest.', 'info')
        return redirect(url_for('contests.predict', contest_id=contest_id))

    # Check USDT balance
    prof = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
    if not prof:
        flash('Profile not found.', 'error')
        return redirect(url_for('contests.index'))

    balance    = float(prof[0].get('balance') or 0)
    entry_fee  = float(contest.get('entry_fee_usdt') or ENTRY_FEE)

    if balance < entry_fee:
        flash(f'Insufficient USDT balance. Need ${entry_fee:.2f} to enter.', 'error')
        return redirect(url_for('contests.index'))

    # Deduct fee & create entry
    try:
        db.table('profiles').update(
            {'balance': round(balance - entry_fee, 2)}
        ).eq('id', uid).execute()

        db.table('contest_entries').insert({
            'contest_id': contest_id,
            'user_id':    uid,
            'paid':       True,
            'paid_at':    now,
        }).execute()

        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'contest_entry',
            'amount':      -entry_fee,
            'description': f'Contest entry fee — {contest["name"]}',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        flash(f'Joined "{contest["name"]}"! Now submit your predictions.', 'success')
        return redirect(url_for('contests.predict', contest_id=contest_id))

    except Exception as e:
        flash(f'Error joining contest: {e}', 'error')
        return redirect(url_for('contests.index'))


# ─────────────────────────────────────────────
# PREDICT PAGE (form for each match)
# ─────────────────────────────────────────────
@contests_bp.route('/predict/<contest_id>')
@login_required
def predict(contest_id):
    db  = _db()
    uid = session['user_id']

    # Verify user is entered
    entry = _q(lambda: db.table('contest_entries')
               .select('*').eq('contest_id', contest_id).eq('user_id', uid).execute())
    if not entry or not entry[0].get('paid'):
        flash('You must join this contest first.', 'error')
        return redirect(url_for('contests.index'))

    # Load contest
    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    contest = contest_rows[0] if contest_rows else {}

    # Load matches for this contest
    cm_rows = _q(lambda: db.table('contest_matches')
                 .select('match_id').eq('contest_id', contest_id).execute())
    match_ids = [r['match_id'] for r in cm_rows]

    matches = []
    for mid in match_ids:
        rows = _q(lambda: db.table('football_matches')
                  .select('*').eq('id', mid).execute())
        if rows:
            matches.append(rows[0])

    # Existing predictions by this user
    existing_preds = _q(lambda: db.table('predictions')
                        .select('*').eq('contest_id', contest_id).eq('user_id', uid).execute())
    pred_map = {p['match_id']: p for p in existing_preds}

    return render_template('football/predict.html',
        contest=contest,
        matches=matches,
        pred_map=pred_map,
    )


# ─────────────────────────────────────────────
# SUBMIT PREDICTIONS
# ─────────────────────────────────────────────
@contests_bp.route('/predict/<contest_id>/submit', methods=['POST'])
@login_required
def submit_predictions(contest_id):
    db  = _db()
    uid = session['user_id']
    now = _now()

    # Verify entry
    entry = _q(lambda: db.table('contest_entries')
               .select('*').eq('contest_id', contest_id).eq('user_id', uid).execute())
    if not entry or not entry[0].get('paid'):
        flash('You must join this contest first.', 'error')
        return redirect(url_for('contests.index'))

    # Load contest matches
    cm_rows = _q(lambda: db.table('contest_matches')
                 .select('match_id').eq('contest_id', contest_id).execute())
    match_ids = [r['match_id'] for r in cm_rows]

    saved = 0
    for mid in match_ids:
        winner  = request.form.get(f'winner_{mid}', '').strip()
        h_score = request.form.get(f'home_score_{mid}', '0')
        a_score = request.form.get(f'away_score_{mid}', '0')
        scorer  = request.form.get(f'first_scorer_{mid}', '').strip()
        corners = request.form.get(f'corners_{mid}', '0')

        if not winner:
            continue  # skip if user didn't fill this match

        try:
            h_score = int(h_score)
            a_score = int(a_score)
            corners = int(corners)
        except ValueError:
            h_score = a_score = corners = 0

        # Upsert prediction (update if exists)
        existing = _q(lambda: db.table('predictions')
                      .select('id').eq('contest_id', contest_id)
                      .eq('match_id', mid).eq('user_id', uid).execute())

        payload = {
            'contest_id':            contest_id,
            'match_id':              mid,
            'user_id':               uid,
            'predicted_winner':      winner,
            'predicted_home_score':  h_score,
            'predicted_away_score':  a_score,
            'predicted_first_scorer': scorer,
            'predicted_corners':     corners,
            'created_at':            now,
        }

        if existing:
            db.table('predictions').update(payload).eq('id', existing[0]['id']).execute()
        else:
            db.table('predictions').insert(payload).execute()

        saved += 1

    flash(f'Saved {saved} prediction(s)! Good luck!', 'success')
    return redirect(url_for('contests.predict', contest_id=contest_id))


# ─────────────────────────────────────────────
# SCORING ALGORITHM (called by admin after match ends)
# ─────────────────────────────────────────────
def score_match(contest_id: str, match_id: str):
    """
    Calculate points for every user prediction on this match.
    Call this after admin enters the real match result.

    Points breakdown:
        Correct winner       →  10 pts
        Exact score          →  30 pts
        Correct first scorer →  25 pts
        Correct corners      →  15 pts
        Total max            → 100 pts (but 10+30+25+15 = 80 max with current rules)
    """
    db = _db()

    # Load real result
    match_rows = _q(lambda: db.table('football_matches')
                    .select('*').eq('id', match_id).execute())
    if not match_rows:
        return 0

    match = match_rows[0]
    real_home    = match.get('home_score') or 0
    real_away    = match.get('away_score') or 0
    real_scorer  = (match.get('first_scorer') or '').strip().lower()
    real_corners = match.get('corners') or 0

    # Determine real winner
    if real_home > real_away:
        real_winner = 'home'
    elif real_away > real_home:
        real_winner = 'away'
    else:
        real_winner = 'draw'

    # Load all predictions for this match in this contest
    preds = _q(lambda: db.table('predictions')
               .select('*').eq('contest_id', contest_id)
               .eq('match_id', match_id).execute())

    updated = 0
    for pred in preds:
        pts_winner = pts_score = pts_scorer = pts_corners = 0

        # 1. Correct winner
        if pred.get('predicted_winner') == real_winner:
            pts_winner = 10

        # 2. Exact score
        if (pred.get('predicted_home_score') == real_home and
                pred.get('predicted_away_score') == real_away):
            pts_score = 30

        # 3. First scorer (case-insensitive partial match)
        pred_scorer = (pred.get('predicted_first_scorer') or '').strip().lower()
        if pred_scorer and real_scorer and pred_scorer in real_scorer:
            pts_scorer = 25

        # 4. Corners (exact match ± 0)
        pred_corners = pred.get('predicted_corners') or 0
        if pred_corners == real_corners:
            pts_corners = 15

        total = pts_winner + pts_score + pts_scorer + pts_corners

        db.table('predictions').update({
            'points_winner':       pts_winner,
            'points_exact_score':  pts_score,
            'points_first_scorer': pts_scorer,
            'points_corners':      pts_corners,
            'total_points':        total,
            'scored':              True,
        }).eq('id', pred['id']).execute()

        updated += 1

    # Refresh contest_entries total_points for each user
    _refresh_entry_totals(db, contest_id)

    return updated


def _refresh_entry_totals(db, contest_id: str):
    """Re-sum total points for each user in this contest."""
    entries = _q(lambda: db.table('contest_entries')
                 .select('id, user_id').eq('contest_id', contest_id).execute())

    for entry in entries:
        uid = entry['user_id']
        preds = _q(lambda: db.table('predictions')
                   .select('total_points').eq('contest_id', contest_id)
                   .eq('user_id', uid).eq('scored', True).execute())
        total = sum(p.get('total_points', 0) for p in preds)
        db.table('contest_entries').update({'total_points': total}).eq('id', entry['id']).execute()
