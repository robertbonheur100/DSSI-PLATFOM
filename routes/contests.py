# routes/contests.py
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

contests_bp = Blueprint('contests', __name__)

ENTRY_FEE = 5.00


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
# LIST ALL CONTESTS
# ─────────────────────────────────────────────
@contests_bp.route('/')
@login_required
def index():
    db  = _db()
    uid = session['user_id']

    contests = _q(lambda: db.table('football_contests')
                  .select('*').order('created_at', desc=True).execute())

    entries = _q(lambda: db.table('contest_entries')
                 .select('contest_id').eq('user_id', uid).execute())
    joined_ids = {e['contest_id'] for e in entries}

    return render_template('football/contests.html',
        contests=contests,
        joined_ids=joined_ids,
    )


# ─────────────────────────────────────────────
# CONTEST DETAIL — wè match yo anvan rejwenn
# ─────────────────────────────────────────────
@contests_bp.route('/detail/<contest_id>')
@login_required
def detail(contest_id):
    db  = _db()
    uid = session['user_id']

    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    if not contest_rows:
        flash('Contest not found.', 'error')
        return redirect(url_for('contests.index'))

    contest = contest_rows[0]

    # Match ki nan contest sa a
    cm_rows = _q(lambda: db.table('contest_matches')
                 .select('match_id').eq('contest_id', contest_id).execute())
    match_ids = [r['match_id'] for r in cm_rows]

    matches = []
    for mid in match_ids:
        rows = _q(lambda: db.table('football_matches')
                  .select('*').eq('id', mid).execute())
        if rows:
            matches.append(rows[0])

    # Verifye si user deja rejwenn
    entry = _q(lambda: db.table('contest_entries')
               .select('id').eq('contest_id', contest_id).eq('user_id', uid).execute())
    already_joined = bool(entry)

    # Balans user
    prof = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
    balance = float(prof[0].get('balance') or 0) if prof else 0.0

    entry_fee = float(contest.get('entry_fee_usdt') or ENTRY_FEE)
    can_afford = balance >= entry_fee

    return render_template('football/contest_detail.html',
        contest=contest,
        matches=matches,
        already_joined=already_joined,
        balance=balance,
        can_afford=can_afford,
        entry_fee=entry_fee,
    )


# ─────────────────────────────────────────────
# JOIN A CONTEST
# ─────────────────────────────────────────────
@contests_bp.route('/join/<contest_id>', methods=['POST'])
@login_required
def join(contest_id):
    db  = _db()
    uid = session['user_id']
    now = _now()

    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    if not contest_rows:
        flash('Contest not found.', 'error')
        return redirect(url_for('contests.index'))

    contest = contest_rows[0]

    # Aksepte active ak upcoming
    if contest.get('status') not in ('active', 'upcoming'):
        flash('This contest is not open for registration.', 'error')
        return redirect(url_for('contests.index'))

    # Deja rejwenn?
    existing = _q(lambda: db.table('contest_entries')
                  .select('id').eq('contest_id', contest_id).eq('user_id', uid).execute())
    if existing:
        flash('You already joined this contest.', 'info')
        return redirect(url_for('contests.predict', contest_id=contest_id))

    # Verifye balans
    prof = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
    if not prof:
        flash('Profile not found.', 'error')
        return redirect(url_for('contests.index'))

    balance   = float(prof[0].get('balance') or 0)
    entry_fee = float(contest.get('entry_fee_usdt') or ENTRY_FEE)

    if balance < entry_fee:
        flash(f'Insufficient balance. You need ${entry_fee:.2f} USDT to join. Your balance: ${balance:.2f}', 'error')
        return redirect(url_for('contests.detail', contest_id=contest_id))

    try:
        # Dedui frè
        db.table('profiles').update(
            {'balance': round(balance - entry_fee, 2)}
        ).eq('id', uid).execute()

        # Kreye entry
        db.table('contest_entries').insert({
            'contest_id': contest_id,
            'user_id':    uid,
            'paid':       True,
            'paid_at':    now,
        }).execute()

        # Anrejistre nan transactions
        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'contest_entry',
            'amount':      -entry_fee,
            'description': f'Contest entry — {contest["name"]}',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        flash(f'Joined "{contest["name"]}" successfully! Submit your predictions below.', 'success')
        return redirect(url_for('contests.predict', contest_id=contest_id))

    except Exception as e:
        flash(f'Error joining contest: {e}', 'error')
        return redirect(url_for('contests.detail', contest_id=contest_id))


# ─────────────────────────────────────────────
# PREDICT PAGE
# ─────────────────────────────────────────────
@contests_bp.route('/predict/<contest_id>')
@login_required
def predict(contest_id):
    db  = _db()
    uid = session['user_id']

    # Verifye entry
    entry = _q(lambda: db.table('contest_entries')
               .select('*').eq('contest_id', contest_id).eq('user_id', uid).execute())
    if not entry or not entry[0].get('paid'):
        flash('You must join this contest first.', 'error')
        return redirect(url_for('contests.detail', contest_id=contest_id))

    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    contest = contest_rows[0] if contest_rows else {}

    cm_rows = _q(lambda: db.table('contest_matches')
                 .select('match_id').eq('contest_id', contest_id).execute())
    match_ids = [r['match_id'] for r in cm_rows]

    matches = []
    for mid in match_ids:
        rows = _q(lambda: db.table('football_matches')
                  .select('*').eq('id', mid).execute())
        if rows:
            matches.append(rows[0])

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

    entry = _q(lambda: db.table('contest_entries')
               .select('*').eq('contest_id', contest_id).eq('user_id', uid).execute())
    if not entry or not entry[0].get('paid'):
        flash('You must join this contest first.', 'error')
        return redirect(url_for('contests.index'))

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
            continue

        try:
            h_score = int(h_score)
            a_score = int(a_score)
            corners = int(corners)
        except ValueError:
            h_score = a_score = corners = 0

        existing = _q(lambda: db.table('predictions')
                      .select('id').eq('contest_id', contest_id)
                      .eq('match_id', mid).eq('user_id', uid).execute())

        payload = {
            'contest_id':             contest_id,
            'match_id':               mid,
            'user_id':                uid,
            'predicted_winner':       winner,
            'predicted_home_score':   h_score,
            'predicted_away_score':   a_score,
            'predicted_first_scorer': scorer,
            'predicted_corners':      corners,
            'created_at':             now,
        }

        if existing:
            db.table('predictions').update(payload).eq('id', existing[0]['id']).execute()
        else:
            db.table('predictions').insert(payload).execute()

        saved += 1

    flash(f'Saved {saved} prediction(s)! Good luck! 🍀', 'success')
    return redirect(url_for('contests.predict', contest_id=contest_id))


# ─────────────────────────────────────────────
# SCORING ALGORITHM
# ─────────────────────────────────────────────
def score_match(contest_id: str, match_id: str):
    db = _db()

    match_rows = _q(lambda: db.table('football_matches')
                    .select('*').eq('id', match_id).execute())
    if not match_rows:
        return 0

    match = match_rows[0]
    real_home    = match.get('home_score') or 0
    real_away    = match.get('away_score') or 0
    real_scorer  = (match.get('first_scorer') or '').strip().lower()
    real_corners = match.get('corners') or 0

    if real_home > real_away:
        real_winner = 'home'
    elif real_away > real_home:
        real_winner = 'away'
    else:
        real_winner = 'draw'

    preds = _q(lambda: db.table('predictions')
               .select('*').eq('contest_id', contest_id)
               .eq('match_id', match_id).execute())

    for pred in preds:
        pts_winner = pts_score = pts_scorer = pts_corners = 0

        if pred.get('predicted_winner') == real_winner:
            pts_winner = 10

        if (pred.get('predicted_home_score') == real_home and
                pred.get('predicted_away_score') == real_away):
            pts_score = 30

        pred_scorer = (pred.get('predicted_first_scorer') or '').strip().lower()
        if pred_scorer and real_scorer and pred_scorer in real_scorer:
            pts_scorer = 25

        if (pred.get('predicted_corners') or 0) == real_corners:
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

    _refresh_entry_totals(db, contest_id)
    return len(preds)


def _refresh_entry_totals(db, contest_id: str):
    entries = _q(lambda: db.table('contest_entries')
                 .select('id, user_id').eq('contest_id', contest_id).execute())

    for entry in entries:
        uid = entry['user_id']
        preds = _q(lambda: db.table('predictions')
                   .select('total_points').eq('contest_id', contest_id)
                   .eq('user_id', uid).eq('scored', True).execute())
        total = sum(p.get('total_points', 0) for p in preds)
        db.table('contest_entries').update({'total_points': total}).eq('id', entry['id']).execute()
