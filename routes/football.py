# routes/football.py
# ───────────────────────────────────────────────
# FOOTBALL HUB — matches, standings, leaderboard
# ───────────────────────────────────────────────

import os
import requests
from datetime import date, timedelta
from flask import Blueprint, render_template

from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

football_bp = Blueprint('football', __name__)

API_KEY = os.getenv("FOOTBALL_API_KEY")


def get_matches():
    if not API_KEY:
        print("ERROR: FOOTBALL_API_KEY is missing")
        return {"matches": []}

    headers = {
        "X-Auth-Token": API_KEY
    }

    try:
        response = requests.get(
            "https://api.football-data.org/v4/matches",
            headers=headers,
            timeout=10
        )

        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"Football API error: {e}")
        return {"matches": []}


def _db():
    return get_admin_supabase()


def _safe(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return []


@football_bp.route('/')
@login_required
def hub():
    db = _db()

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    matches_today = _safe(lambda: db.table('football_matches')
                          .select('*')
                          .eq('match_date', today)
                          .execute())

    matches_tomorrow = _safe(lambda: db.table('football_matches')
                             .select('*')
                             .eq('match_date', tomorrow)
                             .execute())

    matches_finished = _safe(lambda: db.table('football_matches')
                             .select('*')
                             .eq('status', 'finished')
                             .limit(20)
                             .execute())

    contests = _safe(lambda: db.table('football_contests')
                     .select('*')
                     .eq('status', 'active')
                     .execute())

    return render_template(
        'football/hub.html',
        matches_today=matches_today,
        matches_tomorrow=matches_tomorrow,
        matches_finished=matches_finished,
        contests=contests
    )


@football_bp.route('/matches')
@login_required
def matches():
    data = get_matches()
    return render_template(
        'football/matches.html',
        matches=data.get("matches", [])
    )


@football_bp.route('/standings')
@login_required
def standings():
    db = _db()

    rows = _safe(lambda: db.table('league_standings')
                 .select('*')
                 .order('league')
                 .order('position')
                 .execute())

    leagues = {}
    for r in rows:
        leagues.setdefault(r.get('league', 'Other'), []).append(r)

    return render_template('football/standings.html', leagues=leagues)


@football_bp.route('/leaderboard')
@login_required
def leaderboard():
    db = _db()

    board = _safe(lambda: db.table('global_leaderboard')
                  .select('*')
                  .order('rank')
                  .limit(50)
                  .execute())

    contests = _safe(lambda: db.table('football_contests')
                     .select('id, name, status')
                     .execute())

    return render_template(
        'football/leaderboard.html',
        board=board,
        contests=contests
    )
