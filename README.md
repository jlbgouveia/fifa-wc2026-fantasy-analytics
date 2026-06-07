# FIFA World Cup 2026 — Fantasy Analytics

Interactive analytics over every FIFA World Cup 2026 player, joining their **official FIFA Fantasy**
attributes (position, price, selection %, starting-XI likelihood) with **club & national-team
statistics** (goals, assists, games, interceptions, saves) per season.

> Statistics were extracted on **5 June 2026** — games played after that date are not included.

## The app

A [Streamlit](https://streamlit.io) app (`app.py`) with three tabs:

- **Player rankings** — rank players by a chosen score, filterable by position(s), competition
  (club / national), season range, country, starting likelihood, market value and minimum games.
  Per-column Excel-style filtering via AG Grid.
- **Per-country** — national-team records (W/D/L, goals for/against) with per-game rates, plus a
  country drill-down.
- **Player lookup** — a player's club/national aggregate with an expandable raw per-season table.

### Score metrics

Defined once in `analytics.py` (`METRIC_FORMULAS`) and shown in the app:

| Metric | Formula |
|--------|---------|
| sum goals and assists | goals + assists |
| goals only / assists only | goals / assists |
| interceptions | interceptions |
| weighted average interceptions, assists, goals | 0.05·INT + 0.25·A + 0.65·G |
| saves | saves (goalkeepers) |
| **real multiplication of goals and assists** (default) | 3·A + G × (FWD ×4, MID ×5, DEF ×6, GK ×7) |

Scores can be shown as a **total** or **per game**.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501. (On Windows you can also double-click `run_app.bat`.)

## Data

| File | Contents |
|------|----------|
| `wc2026_players.csv` / `.parquet` | one row per player: fantasy position, price, starting-XI likelihood |
| `wc2026_player_stats_apifootball.csv` | per player / competition / season stats (club + national) |
| `wc2026_team_stats*.csv` | national-team records |
| `fifa_fantasy_*.json` | cached FIFA Fantasy API responses |

Player/team statistics come from [API-Football](https://www.api-football.com); fantasy data from
the official FIFA Fantasy API. The notebook `wc2026_fantasy.ipynb` shows how the dataset is built.

### Regenerating the data (optional)

Needs an API-Football key in `api_football_key.txt` (git-ignored) and the dev deps:

```bash
pip install -r requirements-dev.txt
python run_apifootball.py     # player stats
python run_team_stats.py      # team records
```

## Note on secrets

`api_football_key.txt` is git-ignored and is **only** needed to regenerate data — the app itself
reads the committed CSVs and needs no key.
