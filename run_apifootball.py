"""Full API-Football run for all 48 WC2026 squads (SEPARATE tables from Sofascore).

Requires the Pro plan (season 2025/26 + 7,500 req/day). Resumable: every response
is cached by fetch_apifootball.get, so re-running skips finished work.

Outputs:
  wc2026_player_stats_apifootball.csv               - detailed long table
  wc2026_player_stats_by_team_season_apifootball.csv- season x team rollup
  wc2026_match_log_apifootball.csv                  - FIFA->API id mapping + confidence
"""
import json
import os
import time
from collections import defaultdict
from pathlib import Path
import polars as pl
import fetch_apifootball as af

PROGRESS = Path("run_apifootball_progress.log")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def rollup(rows):
    SUM = ["games", "started", "minutes", "goals", "assists",
           "tackles", "interceptions", "duels", "duels_won", "saves", "goals_conceded"]
    agg, comps = {}, defaultdict(set)
    for r in rows:
        key = (r["player_id"], r["comp_type"], r["team_name"], r["season"])
        if key not in agg:
            agg[key] = {"player_id": r["player_id"], "apifootball_id": r["apifootball_id"],
                        "display_name": r["display_name"], "country": r["country"],
                        "comp_type": r["comp_type"], "team_name": r["team_name"],
                        "season": r["season"], "season_start_year": r["season_start_year"],
                        **{c: 0 for c in SUM}}
        for c in SUM:
            if r.get(c) is not None:
                agg[key][c] += r[c]
        comps[key].add(r["competition"])
    out = []
    for key, row in agg.items():
        row["n_competitions"] = len(comps[key])
        out.append(row)
    return out


def flush(rows, mlog):
    if rows:
        # infer_schema_length=None: scan all rows (saves/goals_conceded are null for
        # outfield players and only int for GKs, which appear later)
        pl.DataFrame(rows, infer_schema_length=None).write_csv(
            "wc2026_player_stats_apifootball.csv")
        pl.DataFrame(rollup(rows), infer_schema_length=None).write_csv(
            "wc2026_player_stats_by_team_season_apifootball.csv")
    pl.DataFrame(mlog).write_csv("wc2026_match_log_apifootball.csv")


# --- guard: require Pro unless explicitly overridden ---
st = af.status()
plan = st.get("subscription", {}).get("plan")
log(f"Plan={plan}, requests={st.get('requests')}")
if plan == "Free" and not os.environ.get("ALLOW_FREE"):
    raise SystemExit("Free plan detected. Upgrade to Pro, or set ALLOW_FREE=1 to "
                     "run a partial (2022-2024, capped at 100/day).")

players = [p for p in json.load(open("fifa_fantasy_players.json", encoding="utf-8"))
           if p["status"] == "playing"]
squads = json.load(open("fifa_fantasy_squads.json", encoding="utf-8"))
sname = {s["id"]: s["name"] for s in squads}
by_country = defaultdict(list)
for p in players:
    by_country[sname.get(p["squadId"])].append(p)

all_rows, mlog = [], []
counts = defaultdict(int)
countries = sorted(by_country)
log(f"Starting: {len(players)} players across {len(countries)} squads")

for ci, country in enumerate(countries, 1):
    fifa = by_country[country]
    ntid = af.national_team_id(country)
    roster = af.squad(ntid) if ntid else []
    matched = af.match_squad_to_fifa(fifa, roster)
    inv = {p["id"]: p for p in fifa}

    # fallback for FIFA players the squad didn't match
    for p in fifa:
        if p["id"] in matched:
            continue
        aid = af.profile_search(p["lastName"], country)
        if aid:
            matched[p["id"]] = (aid, "fallback")

    for fid, (aid, conf) in matched.items():
        fp = inv[fid]
        nm = (fp.get("knownName") or f"{fp['firstName']} {fp['lastName']}").strip()
        counts[conf] += 1
        try:
            rows = af.player_rows(aid, fid, nm, country, ntid)
        except Exception as e:
            log(f"  stats error {nm}: {type(e).__name__}")
            rows = []
        all_rows.extend(rows)
        mlog.append({"player_id": fid, "name": nm, "country": country,
                     "apifootball_id": aid, "confidence": conf, "n_rows": len(rows)})
    for p in fifa:
        if p["id"] not in matched:
            counts["none"] += 1
            nm = (p.get("knownName") or f"{p['firstName']} {p['lastName']}").strip()
            mlog.append({"player_id": p["id"], "name": nm, "country": country,
                         "apifootball_id": None, "confidence": "none", "n_rows": 0})

    log(f"  [{ci}/{len(countries)}] {country:22s} ntid={ntid} "
        f"matched={len(matched)}/{len(fifa)} rows={len(all_rows)}")
    flush(all_rows, mlog)

flush(all_rows, mlog)
total_matched = sum(v for k, v in counts.items() if k != "none")
log(f"DONE. rows={len(all_rows)} matched={total_matched}/{len(players)} "
    f"conf={dict(counts)}")
