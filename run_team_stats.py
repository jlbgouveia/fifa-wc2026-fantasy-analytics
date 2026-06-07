"""National-team records for all 48 WC2026 teams, from API-Football fixtures.

Per match (team's perspective) we derive goals for/against and W/D/L, then aggregate.
A penalty-shootout result counts as a DRAW (W/D/L is decided on goals incl. extra time),
which is the standard "results" convention. Reuses fetch_apifootball (cached get +
national_team_id). ~192 requests.

Outputs:
  wc2026_team_stats.csv            - detail: per team / season / competition
  wc2026_team_stats_by_season.csv  - rollup: per team / season (sums competitions)
"""
import json
from collections import defaultdict
import polars as pl
import fetch_apifootball as af

SEASONS = [2022, 2023, 2024, 2025]
FINISHED = {"FT", "AET", "PEN"}


def season_label(y):
    return f"{y}/{str(y + 1)[2:]}"


squads = json.load(open("fifa_fantasy_squads.json", encoding="utf-8"))
countries = sorted({s["name"] for s in squads})

detail = []
for country in countries:
    ntid = af.national_team_id(country)
    if not ntid:
        print("  ! no NT id for", country)
        continue
    for y in SEASONS:
        d = af.get("fixtures", team=ntid, season=y)
        recs = defaultdict(lambda: dict(played=0, wins=0, draws=0, losses=0,
                                        goals_for=0, goals_against=0, clean_sheets=0))
        for fx in d.get("response", []):
            if fx["fixture"]["status"]["short"] not in FINISHED:
                continue
            gh, ga = fx["goals"]["home"], fx["goals"]["away"]
            if gh is None or ga is None:
                continue
            home = fx["teams"]["home"]["id"] == ntid
            gf, gag = (gh, ga) if home else (ga, gh)
            r = recs[fx["league"]["name"]]
            r["played"] += 1
            r["goals_for"] += gf
            r["goals_against"] += gag
            if gf > gag:
                r["wins"] += 1
            elif gf == gag:
                r["draws"] += 1
            else:
                r["losses"] += 1
            if gag == 0:
                r["clean_sheets"] += 1
        for comp, r in recs.items():
            detail.append(dict(country=country, team_id=ntid, season=season_label(y),
                               season_start_year=y, competition=comp, **r,
                               goal_diff=r["goals_for"] - r["goals_against"],
                               points=r["wins"] * 3 + r["draws"]))
    print(country, "done")

det = pl.DataFrame(detail)
det.write_csv("wc2026_team_stats.csv")

SUMS = ["played", "wins", "draws", "losses", "goals_for", "goals_against", "clean_sheets"]
roll = (det.group_by(["country", "team_id", "season", "season_start_year"])
        .agg(pl.col(SUMS).sum())
        .with_columns((pl.col("goals_for") - pl.col("goals_against")).alias("goal_diff"),
                      (pl.col("wins") * 3 + pl.col("draws")).alias("points"))
        .sort(["country", "season_start_year"]))
roll.write_csv("wc2026_team_stats_by_season.csv")

print(f"\nDONE. {det['country'].n_unique()} teams · {len(det)} detail rows · {len(roll)} season rows")
