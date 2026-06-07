"""Shared analytics for the WC2026 fantasy dataset.

Pure-ish functions over polars DataFrames, used by BOTH the notebook and app.py
(one source of truth). `load_data()` reads the CSV extractions once.
"""
from __future__ import annotations
import polars as pl

POSITIONS = ["GK", "DEF", "MID", "FWD"]

STARTING_LEVELS = ["Likely Starter", "Maybe Starter", "Unlikely Starter"]

METRICS = [
    "sum goals and assists",
    "goals only",
    "assists only",
    "interceptions",
    "weighted average interceptions, assists, goals",
    "saves",
    "real multiplication of goals and assists",   # assists x3 (all); goals x4 FWD / x5 MID / x6 DEF / x7 GK
]

# Plain-language formula for each metric — single source of truth, rendered in the app
# (and anywhere else) so the explanation can never drift from _score_expr below.
METRIC_FORMULAS = {
    "sum goals and assists": "goals + assists",
    "goals only": "goals",
    "assists only": "assists",
    "interceptions": "interceptions",
    "weighted average interceptions, assists, goals":
        "0.05 x interceptions + 0.25 x assists + 0.65 x goals",
    "saves": "saves (goalkeepers)",
    "real multiplication of goals and assists":
        "3 x assists + goals x position multiplier (FWD x4, MID x5, DEF x6, GK x7)",
}

# How the score is aggregated / what the filters do.
SCORING_NOTES = (
    "All counts are **summed over the selected seasons** (and competition, if one is chosen). "
    "**Score mode** - *per game* divides the score by the player's total games in the selected "
    "competition; *total* is the raw sum. The **Competition** filter changes the score only - "
    "the club_/nt_ breakdown columns always show the full club + national split either way."
)

# fantasy attributes carried onto every stats row
_FANTASY_COLS = [
    "player_id", "display_name", "country", "country_abbr", "group",
    "fantasy_position", "fantasy_price", "percent_selected", "starting_likelihood",
    "total_points", "avg_points", "form", "one_to_watch",
]


def load_data():
    """Return (stats, team_detail, team_season, players).

    `stats` is the per player/competition/season table joined with fantasy attributes.
    """
    players = pl.read_csv("wc2026_players.csv")
    fantasy = players.select(_FANTASY_COLS)
    stats = (
        pl.read_csv("wc2026_player_stats_apifootball.csv", infer_schema_length=None)
          .drop(["display_name", "country"])
          .join(fantasy, on="player_id", how="left")
    )
    stats = stats.select(_FANTASY_COLS + [c for c in stats.columns if c not in _FANTASY_COLS])
    team_detail = pl.read_csv("wc2026_team_stats.csv")
    team_season = pl.read_csv("wc2026_team_stats_by_season.csv")
    return stats, team_detail, team_season, players


def _score_expr(metric: str) -> pl.Expr:
    """Build the score expression. Position-dependent metrics use each row's own
    `fantasy_position`, so the function works for one OR several positions at once."""
    g, a, itc, sv = (pl.col("goals"), pl.col("assists"),
                     pl.col("interceptions"), pl.col("saves"))
    pos = pl.col("fantasy_position")
    if metric == "real multiplication of goals and assists":
        # assists x3 (all positions); goals x4 FWD / x5 MID / x6 DEF / x7 GK
        gm = (pl.when(pos == "FWD").then(4).when(pos == "MID").then(5)
              .when(pos == "DEF").then(6).when(pos == "GK").then(7).otherwise(6))
        return 3 * a + gm * g
    return {
        "sum goals and assists": g + a,
        "goals only": g,
        "assists only": a,
        "interceptions": itc,
        "weighted average interceptions, assists, goals": 0.05 * itc + 0.25 * a + 0.65 * g,
        "saves": sv,
    }[metric]


def rank_players(stats, position, metric="real multiplication of goals and assists",
                 years=None, comp_type=None, country=None, starting_likelihood=None,
                 min_price=None, max_price=None, score_mode="per_game", min_games=0, top=20):
    """Sorted table of players, highest score first.

    position  : one position ('FWD') or several (['FWD', 'MID']). Position-dependent
                metrics use each player's own position.
    metric    : see METRICS.
    min_price / max_price : keep players within this market-value ($M) range. None = open.
    years     : [start, end] on season_start_year, inclusive. None = all seasons.
    comp_type : None (club+national), 'club', or 'national'. ONLY affects the score; the
                club_/nt_ breakdown columns always show the full window either way.
    country   : str or list of country names to keep. None = all.
    starting_likelihood: keep only these starter levels (str or list of STARTING_LEVELS).
                None = all.
    score_mode: 'per_game' (default; score divided by games) or 'total' (raw sum).
    min_games : drop players with fewer than this many games in the selected competition
                (default 0 = no filter). Useful with 'per_game' to avoid tiny-sample inflation.
    top       : number of rows (None = all).

    Output columns: player, nation, club (all clubs played for), market_value,
    club_games/goals/assists, nt_games/goals/assists, interceptions, [saves if GK], score.
    """
    positions = [position] if isinstance(position, str) else list(position)
    positions = [p.upper() for p in positions]
    if metric not in METRICS:
        raise ValueError("metric must be one of " + str(METRICS))
    if comp_type not in (None, "club", "national"):
        raise ValueError("comp_type must be None, 'club' or 'national'")
    if score_mode not in ("per_game", "total"):
        raise ValueError("score_mode must be 'per_game' or 'total'")

    # position(s) / years / country / price define the window; comp_type does NOT filter here.
    base = stats.filter(pl.col("fantasy_position").is_in(positions))
    if years is not None:
        base = base.filter(pl.col("season_start_year").is_between(years[0], years[1]))
    if country is not None:
        wanted = [country] if isinstance(country, str) else list(country)
        base = base.filter(pl.col("country").is_in(wanted))
    if starting_likelihood is not None:
        levels = ([starting_likelihood] if isinstance(starting_likelihood, str)
                  else list(starting_likelihood))
        base = base.filter(pl.col("starting_likelihood").is_in(levels))
    if min_price is not None:
        base = base.filter(pl.col("fantasy_price") >= min_price)
    if max_price is not None:
        base = base.filter(pl.col("fantasy_price") <= max_price)

    # SCORE is the only thing the competition filter changes. fantasy_position is kept
    # so position-dependent metrics score each player by their own position.
    sdf = base if comp_type is None else base.filter(pl.col("comp_type") == comp_type)
    sc = (sdf.group_by(["player_id", "fantasy_position"])
             .agg(pl.col(["goals", "assists", "interceptions", "saves", "games"]).sum())
             .with_columns(pl.col(["goals", "assists", "interceptions", "saves", "games"]).fill_null(0)))
    if min_games:
        sc = sc.filter(pl.col("games") >= min_games)
    score_total = _score_expr(metric)
    score = (pl.when(pl.col("games") > 0).then(score_total / pl.col("games")).otherwise(0.0)
             if score_mode == "per_game" else score_total)
    sc = sc.with_columns(score.round(3).alias("score")).select(["player_id", "score"])

    # identity + interceptions/saves totals — always the FULL window (both comp types)
    ident = (base.group_by(["player_id", "display_name", "country", "fantasy_position",
                            "fantasy_price", "starting_likelihood"])
                 .agg(pl.col(["interceptions", "saves"]).sum())
                 .with_columns(pl.col(["interceptions", "saves"]).fill_null(0)))

    # games/goals/assists split by team type — also always the FULL window, so the club
    # columns stay visible even when the competition filter is set to 'national' (and vice versa)
    def _side(ct, prefix):
        return (base.filter(pl.col("comp_type") == ct)
                  .group_by("player_id")
                  .agg(pl.col(["games", "goals", "assists"]).sum())
                  .rename({"games": prefix + "_games", "goals": prefix + "_goals",
                           "assists": prefix + "_assists"}))
    club_side, nt_side = _side("club", "club"), _side("national", "nt")

    # all clubs the player turned out for in the window (most games first)
    clubs = (base.filter(pl.col("comp_type") == "club")
             .group_by(["player_id", "team_name"]).agg(pl.col("games").sum())
             .sort("games", descending=True)
             .group_by("player_id", maintain_order=True)
             .agg(pl.col("team_name").alias("_list"))
             .with_columns(pl.col("_list").list.join(", ").alias("club"))
             .select(["player_id", "club"]))

    split_cols = ["club_games", "club_goals", "club_assists",
                  "nt_games", "nt_goals", "nt_assists"]
    out = (ident.join(club_side, on="player_id", how="left")
                .join(nt_side, on="player_id", how="left")
                .join(clubs, on="player_id", how="left")
                .join(sc, on="player_id", how="inner")    # keep only players with a score
                .with_columns(pl.col(split_cols).fill_null(0), pl.col("club").fill_null(""))
                .sort("score", descending=True))

    cols = [pl.col("display_name").alias("player"), pl.col("country").alias("nation"),
            pl.col("fantasy_position").alias("position"),
            "club", pl.col("fantasy_price").alias("market_value"),
            "starting_likelihood",
            "club_games", "club_goals", "club_assists",
            "nt_games", "nt_goals", "nt_assists", "interceptions"]
    if "GK" in positions:
        cols.append("saves")
    cols.append("score")
    out = out.select(cols)
    return out.head(top) if top else out


def per_country_stats(team_season, country=None, years=None):
    """National-team records aggregated per country, with per-game rates.

    country : str or list to keep (None = all 48). years : [start, end] inclusive.
    """
    df = team_season
    if years is not None:
        df = df.filter(pl.col("season_start_year").is_between(years[0], years[1]))
    if country is not None:
        wanted = [country] if isinstance(country, str) else list(country)
        df = df.filter(pl.col("country").is_in(wanted))

    cols = ["played", "wins", "draws", "losses", "goals_for", "goals_against", "clean_sheets"]
    return (df.group_by("country").agg(pl.col(cols).sum())
              .with_columns(
                  (pl.col("goals_for") - pl.col("goals_against")).alias("goal_diff"),
                  (pl.col("wins") * 3 + pl.col("draws")).alias("points"),
                  (pl.col("wins") / pl.col("played")).round(3).alias("win_rate"),
                  (pl.col("goals_for") / pl.col("played")).round(2).alias("gf_per_game"),
                  (pl.col("goals_against") / pl.col("played")).round(2).alias("ga_per_game"))
              .sort("win_rate", descending=True))


def player_summary(stats, display_name, years=None):
    """Aggregate a player's output, split by comp_type (club / national) + a total row."""
    df = stats.filter(pl.col("display_name") == display_name)
    if years is not None:
        df = df.filter(pl.col("season_start_year").is_between(years[0], years[1]))
    sumcols = ["games", "minutes", "goals", "assists", "interceptions", "saves"]
    by_type = (df.group_by("comp_type").agg(pl.col(sumcols).sum())
                 .with_columns(pl.col(sumcols).fill_null(0)))
    total = by_type.select(pl.col(sumcols).sum()).with_columns(pl.lit("total").alias("comp_type"))
    return pl.concat([by_type, total.select(by_type.columns)], how="vertical").sort("comp_type")


def player_identity(players, display_name):
    """One-row identity card (position, country, price, ...) for a player."""
    return players.filter(pl.col("display_name") == display_name).select(
        ["display_name", "country", "group", "fantasy_position", "fantasy_price",
         "percent_selected", "starting_likelihood"])


def player_raw(stats, display_name, years=None, comp_type=None):
    """Raw per-season / per-competition stat rows for a player."""
    df = stats.filter(pl.col("display_name") == display_name)
    if years is not None:
        df = df.filter(pl.col("season_start_year").is_between(years[0], years[1]))
    if comp_type is not None:
        df = df.filter(pl.col("comp_type") == comp_type)
    return df.select(["comp_type", "competition", "team_name", "season", "games", "minutes",
                      "goals", "assists", "tackles", "interceptions", "duels", "saves",
                      "rating"]).sort(["comp_type", "season", "competition"])
