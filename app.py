"""WC2026 Fantasy Analytics - Streamlit app.

Run:  streamlit run app.py
All analytics logic lives in analytics.py (shared with the notebook).
Tables use AG Grid for Excel-like per-column filtering / sorting.
"""
import pandas as pd
import polars as pl
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

import analytics as an

st.set_page_config(page_title="WC2026 Fantasy Analytics", layout="wide")


@st.cache_data
def get_data():
    return an.load_data()


def grid(df, base, height=430):
    """Render a polars/pandas frame as an Excel-like AG Grid: every column gets a
    sort + a floating filter box (text/number conditions). The key embeds a content
    hash so the grid refreshes when the data changes but keeps its filters otherwise.
    """
    pdf = df.to_pandas() if hasattr(df, "to_pandas") else df
    gb = GridOptionsBuilder.from_dataframe(pdf)
    gb.configure_default_column(filterable=True, sortable=True, resizable=True,
                                floatingFilter=True)
    h = int(pd.util.hash_pandas_object(pdf, index=False).sum())
    AgGrid(pdf, gridOptions=gb.build(), theme="streamlit", height=height,
           fit_columns_on_grid_load=False, key=f"{base}_{h}")


stats, team_detail, team_season, players = get_data()
ALL_COUNTRIES = sorted(players["country"].unique().to_list())
ALL_NAMES = sorted(stats["display_name"].unique().to_list())

st.title("FIFA World Cup 2026 - Fantasy Analytics")
st.caption(
    "Statistics of all FIFA World Cup 2026 players vs their given fantasy teams, positions, "
    "and prices. Statistics were extracted on **5 June 2026**, so there will be missing stats "
    "on games played after that date."
)

tab_rank, tab_country, tab_player = st.tabs(
    ["Player rankings", "Per-country", "Player lookup"])

# ----------------------------------------------------------------- Rankings
with tab_rank:
    with st.expander("How the scores are computed"):
        for m in an.METRICS:
            st.markdown(f"- **{m}** &nbsp; `{an.METRIC_FORMULAS[m]}`")
        st.markdown(an.SCORING_NOTES)

    c1, c2, c3, c4, c5 = st.columns([2, 2, 1, 1, 1])
    position = c1.multiselect("Positions", an.POSITIONS, default=["FWD"])
    metric = c2.selectbox("Metric", an.METRICS,
                          index=an.METRICS.index("real multiplication of goals and assists"))
    comp = c3.selectbox("Competition", ["all", "club", "national"])
    score_mode = c4.selectbox("Score", ["per game", "total"])
    top = c5.number_input("Top N", min_value=5, max_value=1248, value=20, step=5)
    yr = st.slider("Season start year range", 2022, 2025, (2022, 2025))
    pmin, pmax = float(players["fantasy_price"].min()), float(players["fantasy_price"].max())
    price = st.slider("Market value ($M)", pmin, pmax, (pmin, pmax), step=0.1)
    min_games = st.number_input("Minimum total games", min_value=0, max_value=400,
                                value=0, step=5,
                                help="Drop players with fewer games (useful with per-game scoring)")
    countries = st.multiselect("Filter countries (optional)", ALL_COUNTRIES)
    starting = st.multiselect("Starting likelihood (optional)", an.STARTING_LEVELS)
    show_all = st.checkbox("Show all players (ignore Top N)")

    res = an.rank_players(stats, position or an.POSITIONS, metric, years=list(yr),
                          comp_type=None if comp == "all" else comp,
                          country=countries or None,
                          starting_likelihood=starting or None,
                          min_price=price[0], max_price=price[1],
                          score_mode="per_game" if score_mode == "per game" else "total",
                          min_games=int(min_games),
                          top=None if show_all else int(top))
    st.caption(f"**Score** = {an.METRIC_FORMULAS[metric]}  ·  mode: {score_mode}")
    st.caption(f"{len(res)} players  ·  {', '.join(position) or 'all positions'}  ·  "
               f"years {yr[0]}-{yr[1]}  ·  competition: {comp}")
    grid(res, "rank", height=520)

# --------------------------------------------------------------- Per-country
with tab_country:
    yrc = st.slider("Season start year range", 2022, 2025, (2022, 2025), key="yrc")
    grid(an.per_country_stats(team_season, years=list(yrc)), "country_totals", height=520)
    st.divider()
    country = st.selectbox("Inspect a country", ALL_COUNTRIES)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"{country} - record by season")
        rec = (team_season.filter(pl.col("country") == country)
               .select(["season", "played", "wins", "draws", "losses",
                        "goals_for", "goals_against", "goal_diff", "points"])
               .sort("season"))
        grid(rec, "country_record", height=230)
    with col2:
        st.subheader(f"{country} - top scorers (squad)")
        sc = (stats.filter(pl.col("country") == country)
              .group_by(["display_name", "fantasy_position", "fantasy_price",
                         "starting_likelihood"])
              .agg(pl.col(["goals", "assists"]).sum())
              .sort("goals", descending=True).head(12))
        grid(sc, "country_scorers", height=380)

# --------------------------------------------------------------- Player lookup
with tab_player:
    default = ALL_NAMES.index("Kylian Mbappé") if "Kylian Mbappé" in ALL_NAMES else 0
    name = st.selectbox("Player", ALL_NAMES, index=default)
    r = an.player_identity(players, name).to_dicts()[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Position", r["fantasy_position"])
    m2.metric("Country", r["country"])
    m3.metric("Price", f"${r['fantasy_price']}m")
    m4.metric("Selected %", f"{r['percent_selected']}%")

    st.subheader("Aggregate output (club / national / total)")
    grid(an.player_summary(stats, name), "player_summary", height=160)
    with st.expander("Raw per-season / per-competition stats", expanded=True):
        grid(an.player_raw(stats, name), "player_raw", height=420)
