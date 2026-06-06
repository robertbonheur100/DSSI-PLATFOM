# routes/football.py
import os
import requests
from datetime import timedelta, datetime, timezone
from flask import Blueprint, render_template
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

football_bp = Blueprint('football', __name__)
API_KEY = os.getenv("FOOTBALL_API_KEY")

LEAGUES = [
    {"id": 2021, "name": "Premier League",   "flag": "ENG"},
    {"id": 2014, "name": "La Liga",          "flag": "ESP"},
    {"id": 2019, "name": "Serie A",          "flag": "ITA"},
    {"id": 2002, "name": "Bundesliga",       "flag": "GER"},
    {"id": 2015, "name": "Ligue 1",          "flag": "FRA"},
    {"id": 2001, "name": "Champions League", "flag": "UCL"},
    {"id": 2000, "name": "World Cup",        "flag": "WC"},
]


def _db():
    return get_admin_supabase()


def _safe(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return []


def _api_get(path, params=None):
    if not API_KEY:
        return None
    try:
        res = requests.get(
            f"https://api.football-data.org/v4/{path}",
            headers={"X-Auth-Token": API_KEY},
            params=params or {},
            timeout=10
        )
        if res.status_code == 200:
            return res.json()
        print(f"[API {res.status_code}] {path}")
        return None
    except Exception as e:
        print(f"[API ERROR] {e}")
        return None


def _get_api_matches(date_from=None, date_to=None, status=None):
    params = {}
    if date_from:
        params['dateFrom'] = date_from
    if date_to:
        params['dateTo'] = date_to
    if status:
        params['status'] = status

    data = _api_get("matches", params)
    if not data:
        return []

    converted = []
    for m in data.get("matches", []):
        home       = m.get("homeTeam", {})
        away       = m.get("awayTeam", {})
        ft         = m.get("score", {}).get("fullTime", {})
        api_status = m.get("status", "SCHEDULED")

        if api_status in ("IN_PLAY", "PAUSED", "HALFTIME"):
            status_mapped = "live"
        elif api_status == "FINISHED":
            status_mapped = "finished"
        else:
            status_mapped = "scheduled"

        utc_date = m.get("utcDate", "")
        converted.append({
            "id":         m.get("id"),
            "home_team":  home.get("name", "-"),
            "away_team":  away.get("name", "-"),
            "home_logo":  home.get("crest", ""),
            "away_logo":  away.get("crest", ""),
            "league":     m.get("competition", {}).get("name", "-"),
            "match_date": utc_date[:10] if utc_date else "",
            "match_time": utc_date[11:16] if len(utc_date) > 10 else "",
            "status":     status_mapped,
            "home_score": ft.get("home"),
            "away_score": ft.get("away"),
        })
    return converted


def _get_api_standings(competition_id):
    data = _api_get(f"competitions/{competition_id}/standings")
    if not data:
        return []

    for s in data.get("standings", []):
        if s.get("type") == "TOTAL":
            teams = []
            for row in s.get("table", []):
                team = row.get("team", {})
                teams.append({
                    "position":      row.get("position", 0),
                    "team_name":     team.get("name", "-"),
                    "team_logo":     team.get("crest", ""),
                    "played":        row.get("playedGames", 0),
                    "won":           row.get("won", 0),
                    "drawn":         row.get("draw", 0),
                    "lost":          row.get("lost", 0),
                    "goals_for":     row.get("goalsFor", 0),
                    "goals_against": row.get("goalsAgainst", 0),
                    "goal_diff":     row.get("goalDifference", 0),
                    "points":        row.get("points", 0),
                    "form":          row.get("form", ""),
                })
            return teams
    return []


# ─────────────────────────────────────────────
# HUB
# ─────────────────────────────────────────────
@football_bp.route('/')
@login_required
def hub():
    now      = datetime.now(timezone.utc)
    today    = now.strftime('%Y-%m-%d')
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    week_end = (now + timedelta(days=7)).strftime('%Y-%m-%d')
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')

    matches_today    = _get_api_matches(date_from=today, date_to=today)
    matches_tomorrow = _get_api_matches(date_from=tomorrow, date_to=week_end)
    matches_finished = _get_api_matches(
        date_from=week_ago, date_to=today, status="FINISHED"
    )[:20]

    db = _db()
    contests = _safe(lambda: db.table('football_contests')
                     .select('*')
                     .in_('status', ['active', 'upcoming'])
                     .order('created_at', desc=True)
                     .execute())

    return render_template(
        'football/hub.html',
        matches_today=matches_today,
        matches_tomorrow=matches_tomorrow,
        matches_finished=matches_finished,
        contests=contests
    )


# ─────────────────────────────────────────────
# MATCHES
# ─────────────────────────────────────────────
@football_bp.route('/matches')
@login_required
def matches():
    now   = datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    return render_template(
        'football/matches.html',
        matches=_get_api_matches(date_from=today, date_to=today)
    )


# ─────────────────────────────────────────────
# STANDINGS
# ─────────────────────────────────────────────
@football_bp.route('/standings')
@login_required
def standings():
    leagues_data = []

    for league in LEAGUES:
        teams = _get_api_standings(league["id"])
        if teams:
            leagues_data.append({
                "name":  league["name"],
                "flag":  league["flag"],
                "id":    league["id"],
                "teams": teams,
            })

    if not leagues_data:
        db   = _db()
        rows = _safe(lambda: db.table('league_standings')
                     .select('*').order('league').order('position').execute())
        db_leagues = {}
        for r in rows:
            db_leagues.setdefault(r.get('league', 'Other'), []).append(r)

        for lname, teams in db_leagues.items():
            leagues_data.append({
                "name":  lname,
                "flag":  "DB",
                "id":    None,
                "teams": teams,
            })

    return render_template(
        'football/standings.html',
        leagues_data=leagues_data,
        api_ok=bool(API_KEY)
    )


# ─────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────
@football_bp.route('/leaderboard')
@login_required
def leaderboard():
    db = _db()
    board    = _safe(lambda: db.table('global_leaderboard')
                     .select('*').order('rank').limit(50).execute())
    contests = _safe(lambda: db.table('football_contests')
                     .select('id, name, status').execute())
    return render_template(
        'football/leaderboard.html',
        board=board,
        contests=contests
    )


# ─────────────────────────────────────────────
# CONTEST LEADERBOARD — ak participants
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

    # Tout patisipan yo ki peye
    entry_rows = _safe(lambda: db.table('contest_entries')
                       .select('*').eq('contest_id', contest_id)
                       .eq('paid', True)
                       .order('total_points', desc=True).execute())

    # Ajoute username pou chak patisipan
    participants = []
    for e in entry_rows:
        uid  = e['user_id']
        prof = _safe(lambda: db.table('profiles')
                     .select('username').eq('id', uid).execute())
        username = prof[0]['username'] if prof else '—'
        participants.append({
            'username':     username,
            'total_points': e.get('total_points', 0),
            'paid_at':      e.get('paid_at', ''),
            'created_at':   e.get('created_at', ''),
        })

    # Leaderboard = sèlman moun ki gen pwen
    board = [p for p in participants if (p['total_points'] or 0) > 0]
    board.sort(key=lambda x: x['total_points'], reverse=True)

    return render_template(
        'football/contest_leaderboard.html',
        contest=contest,
        participants=participants,
        board=board
    )
