# routes/football.py
# ──────────────────────────────────────────────────────────────
#  FOOTBALL HUB — matches, standings, leaderboard
# ──────────────────────────────────────────────────────────────
import os
import requests
from datetime import date, timedelta
from flask import Blueprint, render_template, session
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

API_KEY = os.getenv("FOOTBALL_API_KEY")

def get_matches():
    headers = {
        "X-Auth-Token": API_KEY
    }

    response = requests.get(
        "https://api.football-data.org/v4/matches",
        headers=headers
    )

    return response.json()

football_bp = Blueprint('football', __name__)


def _db():
    return get_admin_supabase()


def _q(fn):
    """Safe query wrapper — returns [] on error."""
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[Football query error] {e}")
        return []


# ─────────────────────────────────────────────
# HUB HOME — today / tomorrow / finished
# ─────────────────────────────────────────────
@football_bp.route('/')
@login_required
def hub():
    db = _db()
    today    = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    matches_today    = _q(lambda: db.table('football_matches')
                          .select('*').eq('match_date', today)
                          .order('match_time').execute())

    matches_tomorrow = _q(lambda: db.table('football_matches')
                          .select('*').eq('match_date', tomorrow)
                          .order('match_time').execute())

    # Last 20 finished results
    matches_finished = _q(lambda: db.table('football_matches')
                          .select('*').eq('status', 'finished')
                          .order('match_date', desc=True).limit(20).execute())

    # Active contests the user can join
    contests = _q(lambda: db.table('football_contests')
                  .select('*').eq('status', 'active').execute())

    return render_template('football/hub.html',
        matches_today=matches_today,
        matches_tomorrow=matches_tomorrow,
        matches_finished=matches_finished,
        contests=contests,
    )


# ─────────────────────────────────────────────
# LEAGUE STANDINGS
# ─────────────────────────────────────────────
@football_bp.route('/standings')
@login_required
def standings():
    db = _db()

    # Get all standings grouped by league
    rows = _q(lambda: db.table('league_standings')
              .select('*').order('league').order('position').execute())

    # Group into dict  { "Premier League": [...], "La Liga": [...] }
    leagues = {}
    for row in rows:
        lg = row.get('league', 'Other')
        leagues.setdefault(lg, []).append(row)

    return render_template('football/standings.html', leagues=leagues)


# ─────────────────────────────────────────────
# GLOBAL LEADERBOARD
# ─────────────────────────────────────────────
@football_bp.route('/leaderboard')
@login_required
def leaderboard():
    db = _db()

    # Read from the view we created in SQL
    board = _q(lambda: db.table('global_leaderboard')
               .select('*').order('rank').limit(50).execute())

    # Also load all contests for the per-contest tab
    contests = _q(lambda: db.table('football_contests')
                  .select('id, name, status').order('created_at', desc=True).execute())

    return render_template('football/leaderboard.html',
        board=board,
        contests=contests,
    )


# ─────────────────────────────────────────────
# CONTEST LEADERBOARD (per contest)
# ─────────────────────────────────────────────
@football_bp.route('/leaderboard/<contest_id>')
@login_required
def contest_leaderboard(contest_id):
    db = _db()

    contest_rows = _q(lambda: db.table('football_contests')
                      .select('*').eq('id', contest_id).execute())
    if not contest_rows:
        return "Contest not found", 404
    contest = contest_rows[0]

    board = _q(lambda: db.table('contest_leaderboard')
               .select('*').eq('contest_id', contest_id)
               .order('rank').execute())

    return render_template('football/contest_leaderboard.html',
        contest=contest,
        board=board,
    )
