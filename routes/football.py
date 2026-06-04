# routes/football.py
# ───────────────────────────────────────────────
# FOOTBALL HUB — matches, standings, leaderboard
# ───────────────────────────────────────────────
import os
import requests
from datetime import date, timedelta, datetime, timezone
from flask import Blueprint, render_template
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

football_bp = Blueprint('football', __name__)
API_KEY = os.getenv("FOOTBALL_API_KEY")


def _db():
    return get_admin_supabase()


def _safe(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return []


def _get_api_matches(date_from=None, date_to=None, status=None):
    """Rele API football-data.org"""
    if not API_KEY:
        print("ERROR: FOOTBALL_API_KEY manke")
        return []
    headers = {"X-Auth-Token": API_KEY}
    params = {}
    if date_from:
        params['dateFrom'] = date_from
    if date_to:
        params['dateTo'] = date_to
    if status:
        params['status'] = status
    try:
        res = requests.get(
            "https://api.football-data.org/v4/matches",
            headers=headers,
            params=params,
            timeout=10
        )
        res.raise_for_status()
        raw = res.json().get("matches", [])

        converted = []
        for m in raw:
            home      = m.get("homeTeam", {})
            away      = m.get("awayTeam", {})
            score     = m.get("score", {})
            ft        = score.get("fullTime", {})
            ht_score  = ft.get("home")
            at_score  = ft.get("away")
            api_status = m.get("status", "SCHEDULED")

            # Map status API → status nou an
            if api_status in ("IN_PLAY", "PAUSED", "HALFTIME"):
                status_mapped = "live"
            elif api_status == "FINISHED":
                status_mapped = "finished"
            else:
                status_mapped = "scheduled"

            # Ekstrè dat ak lè
            utc_date   = m.get("utcDate", "")
            match_date = utc_date[:10] if utc_date else ""
            match_time = utc_date[11:16] if len(utc_date) > 10 else ""

            converted.append({
                "id":         m.get("id"),
                "home_team":  home.get("name", "—"),
                "away_team":  away.get("name", "—"),
                "home_logo":  home.get("crest", ""),
                "away_logo":  away.get("crest", ""),
                "league":     m.get("competition", {}).get("name", "—"),
                "match_date": match_date,
                "match_time": match_time,
                "status":     status_mapped,
                "home_score": ht_score,
                "away_score": at_score,
            })
        return converted
    except Exception as e:
        print(f"[API ERROR] {e}")
        return []


# ─────────────────────────────────────────────
# HUB — TODAY / TOMORROW / FINISHED
# ─────────────────────────────────────────────
@football_bp.route('/')
@login_required
def hub():
    now      = datetime.now(timezone.utc)
    today    = now.strftime('%Y-%m-%d')
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    week_end = (now + timedelta(days=7)).strftime('%Y-%m-%d')
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')

    # Match jodi a
    matches_today = _get_api_matches(date_from=today, date_to=today)

    # Match demen + 7 jou kap vini
    matches_tomorrow = _get_api_matches(date_from=tomorrow, date_to=week_end)

    # Match fini 7 jou pase
    matches_finished = _get_api_matches(date_from=week_ago, date_to=today, status="FINISHED")
    matches_finished = matches_finished[:20]

    # Contests soti Supabase
    db = _db()
    contests = _safe(lambda: db.table('football_contests')
                     .select('*').eq('status', 'active').execute())

    return render_template(
        'football/hub.html',
        matches_today=matches_today,
        matches_tomorrow=matches_tomorrow,
        matches_finished=matches_finished,
        contests=contests
    )


# ─────────────────────────────────────────────
# PAGE MATCHES API (raw)
# ─────────────────────────────────────────────
@football_bp.route('/matches')
@login_required
def matches():
    now   = datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    all_matches = _get_api_matches(date_from=today, date_to=today)
    return render_template(
        'football/matches.html',
        matches=all_matches
    )


# ─────────────────────────────────────────────
# STANDINGS
# ─────────────────────────────────────────────
@football_bp.route('/standings')
@login_required
def standings():
    db   = _db()
    rows = _safe(lambda: db.table('league_standings')
                 .select('*').order('league').order('position').execute())
    leagues = {}
    for r in rows:
        leagues.setdefault(r.get('league', 'Other'), []).append(r)
    return render_template('football/standings.html', leagues=leagues)


# ─────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────
@football_bp.route('/leaderboard')
@login_required
def leaderboard():
    db = _db()
    board = _safe(lambda: db.table('global_leaderboard')
                  .select('*').order('rank').limit(50).execute())
    contests = _safe(lambda: db.table('football_contests')
                     .select('id, name, status').execute())
    return render_template(
        'football/leaderboard.html',
        board=board,
        contests=contests
    )


# ─────────────────────────────────────────────
# CONTEST LEADERBOARD
# ─────────────────────────────────────────────
@football_bp.route('/leaderboard/<contest_id>')
@login_required
def contest_leaderboard(contest_id):
    db = _db()
    contest_rows = _safe(lambda: db.table('football_contests')
                         .select('*').eq('id', contest_id).execute())
    if not contest_rows:
        return "Contest not found", 404
    contest = contest_rows[0]
    board = _safe(lambda: db.table('contest_leaderboard')
                  .select('*').eq('contest_id', contest_id)
                  .order('rank').execute())
    return render_template(
        'football/contest_leaderboard.html',
        contest=contest,
        board=board
    )
