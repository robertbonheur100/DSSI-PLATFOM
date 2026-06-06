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

TTL = {
    "live":      15,
    "today":     30,
    "upcoming":  360,
    "finished":  360,
    "standings": 720,
}


def _db():
    return get_admin_supabase()


def _safe(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return []


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _cache_get(db, cache_key, ttl_minutes):
    try:
        res = db.table('api_cache') \
            .select('data, cached_at') \
            .eq('cache_key', cache_key) \
            .execute()

        if not res.data:
            return None

        row       = res.data[0]
        cached_at = datetime.fromisoformat(
            row['cached_at'].replace('Z', '+00:00')
        )
        age_minutes = (datetime.now(timezone.utc) - cached_at).total_seconds() / 60

        if age_minutes < ttl_minutes:
            return row['data']

        return None

    except Exception as e:
        print(f"[CACHE GET ERROR] {e}")
        return None


def _cache_set(db, cache_key, data):
    try:
        existing = db.table('api_cache') \
            .select('id') \
            .eq('cache_key', cache_key) \
            .execute()

        if existing.data:
            db.table('api_cache').update({
                'data':      data,
                'cached_at': _now_iso(),
            }).eq('cache_key', cache_key).execute()
        else:
            db.table('api_cache').insert({
                'cache_key': cache_key,
                'data':      data,
                'cached_at': _now_iso(),
            }).execute()

    except Exception as e:
        print(f"[CACHE SET ERROR] {e}")


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


def _convert_match(m):
    home       = m.get("homeTeam", {})
    away       = m.get("awayTeam", {})
    ft         = m.get("score", {}).get("fullTime", {})
    ht         = m.get("score", {}).get("halfTime", {})
    api_status = m.get("status", "SCHEDULED")

    if api_status in ("IN_PLAY", "PAUSED", "HALFTIME"):
        status_mapped = "live"
    elif api_status == "FINISHED":
        status_mapped = "finished"
    else:
        status_mapped = "scheduled"

    utc_date = m.get("utcDate", "")
    return {
        "id":          m.get("id"),
        "home_team":   home.get("name", "-"),
        "away_team":   away.get("name", "-"),
        "home_logo":   home.get("crest", ""),
        "away_logo":   away.get("crest", ""),
        "league":      m.get("competition", {}).get("name", "-"),
        "league_logo": m.get("competition", {}).get("emblem", ""),
        "matchday":    m.get("matchday"),
        "match_date":  utc_date[:10] if utc_date else "",
        "match_time":  utc_date[11:16] if len(utc_date) > 10 else "",
        "status":      status_mapped,
        "api_status":  api_status,
        "home_score":  ft.get("home"),
        "away_score":  ft.get("away"),
        "home_ht":     ht.get("home"),
        "away_ht":     ht.get("away"),
        "minute":      m.get("minute"),
        "venue":       m.get("venue", ""),
        "referee":     m.get("referees", [{}])[0].get("name", "") if m.get("referees") else "",
    }


def _get_matches_today():
    db    = _db()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    key   = f"matches_today_{today}"
    cached = _cache_get(db, key, TTL["today"])
    if cached is not None:
        return cached
    data = _api_get("matches", {"dateFrom": today, "dateTo": today})
    if not data:
        return []
    result = [_convert_match(m) for m in data.get("matches", [])]
    _cache_set(db, key, result)
    return result


def _get_matches_live():
    db  = _db()
    key = "matches_live"
    cached = _cache_get(db, key, TTL["live"])
    if cached is not None:
        return cached
    data = _api_get("matches", {"status": "LIVE"})
    if not data:
        data = _api_get("matches", {"status": "IN_PLAY"})
    if not data:
        return []
    result = [_convert_match(m) for m in data.get("matches", [])]
    _cache_set(db, key, result)
    return result


def _get_matches_upcoming():
    db       = _db()
    now      = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    week_end = (now + timedelta(days=7)).strftime('%Y-%m-%d')
    key      = f"matches_upcoming_{tomorrow}_{week_end}"
    cached = _cache_get(db, key, TTL["upcoming"])
    if cached is not None:
        return cached
    data = _api_get("matches", {"dateFrom": tomorrow, "dateTo": week_end})
    if not data:
        return []
    result = [_convert_match(m) for m in data.get("matches", [])]
    _cache_set(db, key, result)
    return result


def _get_matches_finished():
    db       = _db()
    now      = datetime.now(timezone.utc)
    today    = now.strftime('%Y-%m-%d')
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    key      = f"matches_finished_{week_ago}_{today}"
    cached = _cache_get(db, key, TTL["finished"])
    if cached is not None:
        return cached
    data = _api_get("matches", {
        "dateFrom": week_ago,
        "dateTo":   today,
        "status":   "FINISHED"
    })
    if not data:
        return []
    result = [_convert_match(m) for m in data.get("matches", [])][:30]
    _cache_set(db, key, result)
    return result


def _get_api_standings(competition_id):
    db  = _db()
    key = f"standings_{competition_id}"
    cached = _cache_get(db, key, TTL["standings"])
    if cached is not None:
        return cached
    data = _api_get(f"competitions/{competition_id}/standings")
    if not data:
        return []
    teams = []
    for s in data.get("standings", []):
        if s.get("type") == "TOTAL":
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
            break
    if teams:
        _cache_set(db, key, teams)
    return teams


# ─────────────────────────────────────────────
# HUB
# ─────────────────────────────────────────────
@football_bp.route('/')
@login_required
def hub():
    matches_live  = _get_matches_live()
    matches_today = _get_matches_today()
    live_ids      = {m["id"] for m in matches_live}
    matches_today = [m for m in matches_today if m["id"] not in live_ids]
    matches_tomorrow = _get_matches_upcoming()
    matches_finished = _get_matches_finished()

    db = _db()
    contests = _safe(lambda: db.table('football_contests')
                     .select('*')
                     .in_('status', ['active', 'upcoming'])
                     .order('created_at', desc=True)
                     .execute())

    return render_template(
        'football/hub.html',
        matches_live=matches_live,
        matches_today=matches_today,
        matches_tomorrow=matches_tomorrow,
        matches_finished=matches_finished,
        contests=contests
    )


# ─────────────────────────────────────────────
# MATCHES PAGE
# ─────────────────────────────────────────────
@football_bp.route('/matches')
@login_required
def matches():
    matches_live  = _get_matches_live()
    matches_today = _get_matches_today()
    live_ids      = {m["id"] for m in matches_live}
    matches_today = [m for m in matches_today if m["id"] not in live_ids]
    return render_template(
        'football/matches.html',
        matches_live=matches_live,
        matches_today=matches_today,
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
# CONTEST LEADERBOARD — KORIJE
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

    # Tout patisipan ki peye
    entry_rows = _safe(lambda: db.table('contest_entries')
                       .select('*').eq('contest_id', contest_id)
                       .eq('paid', True)
                       .order('total_points', desc=True).execute())

    # Jwenn tout user IDs yon sèl fwa
    user_ids = [e['user_id'] for e in entry_rows]

    profiles = {}
    if user_ids:
        try:
            prof_res = db.table('profiles') \
                .select('id, username') \
                .in_('id', user_ids) \
                .execute()
            for p in (prof_res.data or []):
                profiles[p['id']] = p['username']
        except Exception as e:
            print(f"[PROFILES ERROR] {e}")

    # Konstui liste patisipan
    participants = []
    for e in entry_rows:
        participants.append({
            'username':     profiles.get(e['user_id'], '—'),
            'total_points': e.get('total_points', 0) or 0,
            'paid_at':      e.get('paid_at', ''),
            'created_at':   e.get('created_at', ''),
        })

    # Leaderboard = sèlman moun ki gen pwen
    board = [p for p in participants if p['total_points'] > 0]
    board.sort(key=lambda x: x['total_points'], reverse=True)

    return render_template(
        'football/contest_leaderboard.html',
        contest=contest,
        participants=participants,
        board=board
    )
