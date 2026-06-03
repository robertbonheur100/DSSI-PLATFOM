# routes/admin_football.py
# ──────────────────────────────────────────────────────────────
#  ADMIN — Football management panel
# ──────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils.supabase_client import get_admin_supabase
from utils.helpers import admin_required
from routes.contests import score_match   # scoring algorithm

admin_football_bp = Blueprint('admin_football', __name__)


def _db():
    return get_admin_supabase()


def _q(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[AdminFootball query error] {e}")
        return []


def _now():
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# ADMIN FOOTBALL DASHBOARD
# ─────────────────────────────────────────────
@admin_football_bp.route('/')
@admin_required
def dashboard():
    db = _db()

    matches  = _q(lambda: db.table('football_matches')
                  .select('*').order('match_date', desc=True).limit(50).execute())
    contests = _q(lambda: db.table('football_contests')
                  .select('*').order('created_at', desc=True).execute())
    standings = _q(lambda: db.table('league_standings')
                   .select('*').order('league').order('position').execute())

    return render_template('football/admin_football.html',
        matches=matches,
        contests=contests,
        standings=standings,
    )


# ─────────────────────────────────────────────
# CREATE MATCH
# ─────────────────────────────────────────────
@admin_football_bp.route('/match/create', methods=['POST'])
@admin_required
def create_match():
    db = _db()

    try:
        db.table('football_matches').insert({
            'home_team':  request.form.get('home_team', '').strip(),
            'away_team':  request.form.get('away_team', '').strip(),
            'home_logo':  request.form.get('home_logo', '').strip() or None,
            'away_logo':  request.form.get('away_logo', '').strip() or None,
            'league':     request.form.get('league', '').strip(),
            'match_date': request.form.get('match_date', ''),
            'match_time': request.form.get('match_time', '') or None,
            'status':     'scheduled',
        }).execute()
        flash('Match created.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# UPDATE MATCH STATUS
# ─────────────────────────────────────────────
@admin_football_bp.route('/match/<match_id>/status', methods=['POST'])
@admin_required
def update_match_status(match_id):
    db     = _db()
    status = request.form.get('status', 'scheduled')

    try:
        db.table('football_matches').update({'status': status}).eq('id', match_id).execute()
        flash(f'Match status → {status}', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# ENTER MATCH RESULT (triggers scoring)
# ─────────────────────────────────────────────
@admin_football_bp.route('/match/<match_id>/result', methods=['POST'])
@admin_required
def enter_result(match_id):
    db = _db()

    try:
        home_score   = int(request.form.get('home_score', 0))
        away_score   = int(request.form.get('away_score', 0))
        first_scorer = request.form.get('first_scorer', '').strip()
        corners      = int(request.form.get('corners', 0))

        db.table('football_matches').update({
            'home_score':   home_score,
            'away_score':   away_score,
            'first_scorer': first_scorer or None,
            'corners':      corners,
            'status':       'finished',
        }).eq('id', match_id).execute()

        # Auto-score ALL contests that include this match
        cm_rows = _q(lambda: db.table('contest_matches')
                     .select('contest_id').eq('match_id', match_id).execute())

        total_scored = 0
        for row in cm_rows:
            count = score_match(row['contest_id'], match_id)
            total_scored += count

        flash(f'Result saved. Scored {total_scored} prediction(s) across {len(cm_rows)} contest(s).', 'success')

    except Exception as e:
        flash(f'Error entering result: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# CREATE CONTEST
# ─────────────────────────────────────────────
@admin_football_bp.route('/contest/create', methods=['POST'])
@admin_required
def create_contest():
    db = _db()

    try:
        db.table('football_contests').insert({
            'name':           request.form.get('name', '').strip(),
            'description':    request.form.get('description', '').strip() or None,
            'entry_fee_usdt': float(request.form.get('entry_fee', 5.0)),
            'prize_1st':      float(request.form.get('prize_1st', 100.0)),
            'prize_2nd':      float(request.form.get('prize_2nd', 50.0)),
            'status':         'upcoming',
            'is_worldcup':    request.form.get('is_worldcup') == 'on',
            'start_date':     request.form.get('start_date') or None,
            'end_date':       request.form.get('end_date') or None,
        }).execute()
        flash('Contest created.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# CHANGE CONTEST STATUS (activate / finish)
# ─────────────────────────────────────────────
@admin_football_bp.route('/contest/<contest_id>/status', methods=['POST'])
@admin_required
def update_contest_status(contest_id):
    db     = _db()
    status = request.form.get('status', 'upcoming')

    try:
        db.table('football_contests').update({'status': status}).eq('id', contest_id).execute()
        flash(f'Contest status → {status}', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# ADD MATCH TO CONTEST
# ─────────────────────────────────────────────
@admin_football_bp.route('/contest/<contest_id>/add-match', methods=['POST'])
@admin_required
def add_match_to_contest(contest_id):
    db       = _db()
    match_id = request.form.get('match_id', '').strip()

    if not match_id:
        flash('Select a match.', 'error')
        return redirect(url_for('admin_football.dashboard'))

    # Prevent duplicates
    existing = _q(lambda: db.table('contest_matches')
                  .select('id').eq('contest_id', contest_id)
                  .eq('match_id', match_id).execute())
    if existing:
        flash('Match already in contest.', 'info')
        return redirect(url_for('admin_football.dashboard'))

    try:
        db.table('contest_matches').insert({
            'contest_id': contest_id,
            'match_id':   match_id,
        }).execute()
        flash('Match added to contest.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# PAY WINNERS (1st / 2nd place)
# ─────────────────────────────────────────────
@admin_football_bp.route('/contest/<contest_id>/pay-winners', methods=['POST'])
@admin_required
def pay_winners(contest_id):
    db  = _db()
    now = _now()

    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    if not contest_rows:
        flash('Contest not found.', 'error')
        return redirect(url_for('admin_football.dashboard'))

    contest   = contest_rows[0]
    prize_1st = float(contest.get('prize_1st') or 100)
    prize_2nd = float(contest.get('prize_2nd') or 50)

    # Rank by total_points DESC
    entries = _q(lambda: db.table('contest_entries')
                 .select('*').eq('contest_id', contest_id)
                 .eq('paid', True).order('total_points', desc=True).execute())

    if not entries:
        flash('No entries to pay.', 'info')
        return redirect(url_for('admin_football.dashboard'))

    paid_count = 0
    prizes     = [(1, prize_1st), (2, prize_2nd)]

    for rank, prize in prizes:
        idx = rank - 1
        if idx >= len(entries):
            continue

        entry = entries[idx]
        uid   = entry['user_id']

        # Load profile balance
        prof = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
        if not prof:
            continue

        balance = float(prof[0].get('balance') or 0)
        db.table('profiles').update(
            {'balance': round(balance + prize, 2)}
        ).eq('id', uid).execute()

        db.table('contest_entries').update(
            {'rank': rank, 'prize_won': prize}
        ).eq('id', entry['id']).execute()

        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'contest_prize',
            'amount':      prize,
            'description': f'🏆 Contest prize #{rank} — {contest["name"]} (+${prize})',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        paid_count += 1

    # Mark contest finished
    db.table('football_contests').update(
        {'status': 'finished'}
    ).eq('id', contest_id).execute()

    flash(f'Paid {paid_count} winner(s). Contest closed.', 'success')
    return redirect(url_for('admin_football.dashboard'))


# ─────────────────────────────────────────────
# UPDATE LEAGUE STANDINGS
# ─────────────────────────────────────────────
@admin_football_bp.route('/standings/update', methods=['POST'])
@admin_required
def update_standings():
    db = _db()

    league   = request.form.get('league', '').strip()
    season   = request.form.get('season', '2024-25').strip()
    position = int(request.form.get('position', 1))
    team     = request.form.get('team_name', '').strip()

    if not league or not team:
        flash('League and team name required.', 'error')
        return redirect(url_for('admin_football.dashboard'))

    try:
        # Upsert by league + team
        existing = _q(lambda: db.table('league_standings')
                      .select('id').eq('league', league)
                      .eq('team_name', team).execute())

        payload = {
            'league':         league,
            'season':         season,
            'position':       position,
            'team_name':      team,
            'played':         int(request.form.get('played', 0)),
            'won':            int(request.form.get('won', 0)),
            'drawn':          int(request.form.get('drawn', 0)),
            'lost':           int(request.form.get('lost', 0)),
            'goals_for':      int(request.form.get('goals_for', 0)),
            'goals_against':  int(request.form.get('goals_against', 0)),
            'goal_diff':      int(request.form.get('goal_diff', 0)),
            'points':         int(request.form.get('points', 0)),
            'updated_at':     now := _now(),
        }

        if existing:
            db.table('league_standings').update(payload).eq('id', existing[0]['id']).execute()
        else:
            db.table('league_standings').insert(payload).execute()

        flash(f'Standings updated for {team}.', 'success')

    except Exception as e:
        flash(f'Error: {e}', 'error')

    return redirect(url_for('admin_football.dashboard'))
