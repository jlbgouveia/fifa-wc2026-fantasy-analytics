"""API-Football fetcher for the WC2026 dataset (cross-validation source, kept in
SEPARATE tables from Sofascore).

Matching strategy (no fifaId): for each of the 48 countries we resolve the
national-team id, pull its squad (/players/squads) to get API-Football player
ids directly, and align those to the FIFA fantasy roster by last name + first
initial WITHIN the same country. Players the squad endpoint misses fall back to
/players/profiles?search=. This sidesteps open-web fuzzy search entirely.

Stats: /players?id=&season= returns one block per (team, league); national-team
competitions (Friendlies, Nations League, WC-Qualification ...) come back as
their own blocks, so club vs national splits cleanly.

Key from env API_FOOTBALL_KEY or api_football_key.txt. Direct api-sports host
(NOT RapidAPI) -> header x-apisports-key. Every response cached to disk.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from pathlib import Path

import requests
from rapidfuzz import fuzz
from unidecode import unidecode

BASE = "https://v3.football.api-sports.io"
CACHE_DIR = Path("apifootball_cache")
CACHE_DIR.mkdir(exist_ok=True)
SEASONS = [2022, 2023, 2024, 2025]   # API start-year: 2022=2022/23 ... 2025=2025/26
DELAY = 0.15                          # Pro allows ~300+/min; gentle spacing


def _key() -> str:
    k = os.environ.get("API_FOOTBALL_KEY")
    if not k and Path("api_football_key.txt").exists():
        k = Path("api_football_key.txt").read_text(encoding="utf-8").strip()
    if not k:
        raise SystemExit("No API key (api_football_key.txt or $env:API_FOOTBALL_KEY)")
    return k


_S = requests.Session()
_S.headers.update({"x-apisports-key": _key()})
_last = 0.0


def get(path: str, **params) -> dict:
    """Cached GET. Cache key = path+params. Retries 429/5xx with backoff."""
    global _last
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    ck = hashlib.md5(f"{path}?{qs}".encode()).hexdigest()
    cf = CACHE_DIR / f"{ck}.json"
    if cf.exists():
        return json.loads(cf.read_text(encoding="utf-8"))

    for attempt in range(5):
        dt = time.time() - _last
        if dt < DELAY:
            time.sleep(DELAY - dt)
        _last = time.time()
        try:
            r = _S.get(f"{BASE}/{path}", params=params, timeout=30)
        except Exception:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            j = r.json()
            # Don't cache transient quota/rate errors; DO cache real empty results.
            errs = j.get("errors") or {}
            if isinstance(errs, dict) and ("rateLimit" in errs or "requests" in errs):
                time.sleep(2 + 2 * attempt)
                continue
            cf.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
            return j
        if r.status_code == 429:
            time.sleep(2 + 2 * attempt)
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        return {"response": [], "errors": {"http": r.status_code}}
    return {"response": [], "errors": {"exhausted": True}}


def norm(s: str | None) -> str:
    if not s:
        return ""
    import re
    return re.sub(r"[^a-z ]", "", unidecode(s).lower()).strip()


def status() -> dict:
    return get("status").get("response", {})


# FIFA Fantasy country name -> API-Football national-team name
COUNTRY_TO_AF = {
    "Korea Republic": "South Korea", "IR Iran": "Iran", "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast", "Congo DR": "Congo DR", "Cabo Verde": "Cape Verde",
    "Czechia": "Czech Republic", "Türkiye": "Turkey", "USA": "USA", "Curacao": "Curaçao",
}

# Explicit national-team id overrides for names that don't resolve cleanly
# (accents, "&" vs "and", etc.). Verified against /teams search.
COUNTRY_AF_ID = {
    "Côte d'Ivoire": 1501, "Cote d'Ivoire": 1501,
    "Bosnia and Herzegovina": 1113,
}


def national_team_id(country: str) -> int | None:
    if country in COUNTRY_AF_ID:
        return COUNTRY_AF_ID[country]
    name = COUNTRY_TO_AF.get(country, country)
    for params in ({"name": name}, {"search": name}):
        resp = get("teams", **params).get("response", [])
        for item in resp:
            t = item.get("team", {})
            if t.get("national"):
                return t["id"]
    return None


def squad(team_id: int) -> list[dict]:
    resp = get("players/squads", team=team_id).get("response", [])
    return (resp[0].get("players") if resp else []) or []


def match_squad_to_fifa(fifa_players: list[dict], roster: list[dict]) -> dict:
    """Map FIFA player_id -> (api_id, confidence). fifa_players is one country's
    list of dicts with id/firstName/lastName/knownName. roster from squad()."""
    out = {}
    used = set()
    cand = [{"id": r["id"], "n": norm(r.get("name")), "pos": r.get("position")}
            for r in roster]
    for p in fifa_players:
        last = norm(p["lastName"])
        full = norm(p.get("knownName") or f"{p['firstName']} {p['lastName']}")
        finit = norm(p["firstName"])[:1]
        best, best_score = None, -1
        for c in cand:
            if c["id"] in used:
                continue
            # squad names look like "K. Mbappé" -> compare last token & initial
            toks = c["n"].split()
            c_last = toks[-1] if toks else ""
            c_init = toks[0][:1] if len(toks) > 1 else ""
            sim = max(fuzz.ratio(last, c_last), fuzz.WRatio(full, c["n"]))
            if finit and c_init and finit == c_init:
                sim += 8
            if sim > best_score:
                best, best_score = c, sim
        if best and best_score >= 80:
            used.add(best["id"])
            conf = "high" if best_score >= 92 else "medium"
            out[p["id"]] = (best["id"], conf)
    return out


def profile_search(last_name: str, country: str) -> int | None:
    """Fallback: resolve a player id by surname search, filtered to nationality."""
    resp = get("players/profiles", search=last_name).get("response", [])
    af_country = COUNTRY_TO_AF.get(country, country)
    for item in resp:
        pl = item.get("player", {})
        if norm(pl.get("nationality")) == norm(af_country):
            return pl.get("id")
    return None


def _season_label(y: int) -> str:
    return f"{y}/{str(y + 1)[2:]}"


def player_rows(api_id: int, fifa_id, display_name: str, country: str,
                nt_team_id: int | None) -> list[dict]:
    rows = []
    for y in SEASONS:
        data = get("players", id=api_id, season=y)
        resp = data.get("response", [])
        if not resp:
            continue
        for st in resp[0].get("statistics", []):
            g = st.get("games", {})
            apps, mins = g.get("appearences"), g.get("minutes")
            if not apps and not mins:
                continue  # registered-but-didn't-play block
            team = st.get("team", {})
            league = st.get("league", {})
            tk = st.get("tackles", {})
            du = st.get("duels", {})
            gl = st.get("goals", {})
            national = (nt_team_id is not None and team.get("id") == nt_team_id)
            rows.append({
                "player_id": fifa_id, "apifootball_id": api_id,
                "display_name": display_name, "country": country,
                "competition": league.get("name"),
                "comp_type": "national" if national else "club",
                "team_name": team.get("name"),
                "season": _season_label(y), "season_start_year": y,
                "games": apps, "started": g.get("lineups"), "minutes": mins,
                "goals": gl.get("total"), "assists": gl.get("assists"),
                "tackles": tk.get("total"), "interceptions": tk.get("interceptions"),
                "duels": du.get("total"), "duels_won": du.get("won"),
                "saves": gl.get("saves"), "goals_conceded": gl.get("conceded"),
                "rating": g.get("rating"),
            })
    return rows
