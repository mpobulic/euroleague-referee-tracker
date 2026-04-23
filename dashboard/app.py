"""
Streamlit dashboard – Euroleague Referee Error Tracker

Sections:
  1. Overview   – season-level summary metrics
  2. Referees   – rankings table + per-referee drill-down
  3. Teams      – bias heatmap + per-team analysis
  4. Games      – round browser + game incident log
  5. Incidents  – filterable incident explorer
"""
from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")
DEFAULT_SEASON = os.getenv("DEFAULT_SEASON", "E2024")


# ── Cached API helpers ────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch(path: str, params: dict | None = None) -> list | dict | None:
    try:
        r = httpx.get(f"{API_BASE}{path}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


# ── Layout ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="EuroLeague Referee Tracker",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏀 EuroLeague Referee Error Tracker")
st.caption("AI-powered analysis of referee decisions across the EuroLeague season.")

# Sidebar
with st.sidebar:
    season = st.selectbox("Season", ["E2024", "E2023", "E2022"], index=0)
    section = st.radio(
        "Section",
        ["Overview", "Referees", "Teams", "Games", "Incidents"],
        index=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────
if section == "Overview":
    st.header("Season Overview")

    incidents_data = fetch("/incidents", {"season": season, "limit": 500}) or []
    games_data = fetch("/games", {"season": season}) or []
    refs_data = fetch("/referees") or []

    df_inc = pd.DataFrame(incidents_data)
    df_games = pd.DataFrame(games_data)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Games", len(df_games))
    col2.metric("Total Incidents", len(df_inc))
    col3.metric(
        "High/Critical Incidents",
        len(df_inc[df_inc["severity"].isin(["high", "critical"])]) if not df_inc.empty else 0,
    )
    col4.metric("Referees Active", len(refs_data))

    if not df_inc.empty:
        st.subheader("Incidents by Type")
        fig = px.bar(
            df_inc["incident_type"].value_counts().reset_index(),
            x="incident_type",
            y="count",
            color="incident_type",
            labels={"incident_type": "Type", "count": "Count"},
        )
        st.plotly_chart(fig, use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Severity Distribution")
            fig_sev = px.pie(
                df_inc,
                names="severity",
                color="severity",
                color_discrete_map={
                    "low": "#4CAF50",
                    "medium": "#FF9800",
                    "high": "#F44336",
                    "critical": "#9C27B0",
                },
            )
            st.plotly_chart(fig_sev, use_container_width=True)

        with col_b:
            st.subheader("Incidents Over Rounds")
            if "round_number" in df_inc.columns:
                round_counts = df_inc.groupby("round_number").size().reset_index(name="count")
                fig_rounds = px.line(round_counts, x="round_number", y="count", markers=True)
                st.plotly_chart(fig_rounds, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# REFEREES
# ─────────────────────────────────────────────────────────────────────────────
elif section == "Referees":
    st.header("Referee Rankings")

    min_games = st.slider("Minimum games officiated", 1, 20, 5)
    rankings = fetch("/referees/rankings", {"season": season, "min_games": min_games}) or []
    df = pd.DataFrame(rankings)

    if df.empty:
        st.info("No ranking data available. Run ingestion first.")
    else:
        # Colour-coded accuracy score
        fig = px.bar(
            df.head(20),
            x="referee_name",
            y="accuracy_score",
            color="accuracy_score",
            color_continuous_scale=["red", "orange", "green"],
            range_color=[0, 1],
            labels={"accuracy_score": "Accuracy Score", "referee_name": "Referee"},
            title="Top 20 Referees by Accuracy Score",
        )
        fig.update_traces(texttemplate="%{y:.2f}", textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Full Rankings Table")
        st.dataframe(
            df[["rank", "referee_name", "games_officiated", "accuracy_score", "error_rate", "high_critical_count"]],
            use_container_width=True,
        )

        # Drill-down
        st.subheader("Referee Detail")
        ref_names = df["referee_name"].tolist()
        selected_name = st.selectbox("Select referee", ref_names)
        selected_row = df[df["referee_name"] == selected_name].iloc[0]
        ref_id = int(selected_row["referee_id"])

        stats = fetch(f"/referees/{ref_id}/stats", {"season": season})
        if stats:
            c1, c2, c3 = st.columns(3)
            c1.metric("Games Officiated", stats["games_officiated"])
            c2.metric("Accuracy Score", f"{stats['accuracy_score']:.2%}")
            c3.metric("High/Critical Errors", stats["high_critical_count"])

            col_x, col_y = st.columns(2)
            with col_x:
                sev_df = pd.DataFrame(
                    list(stats["severity_breakdown"].items()), columns=["Severity", "Count"]
                )
                fig_sev = px.pie(sev_df, names="Severity", values="Count", title="By Severity")
                st.plotly_chart(fig_sev, use_container_width=True)
            with col_y:
                type_df = pd.DataFrame(
                    list(stats["incident_type_breakdown"].items()), columns=["Type", "Count"]
                )
                fig_type = px.bar(type_df, x="Type", y="Count", title="By Incident Type")
                st.plotly_chart(fig_type, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# TEAMS
# ─────────────────────────────────────────────────────────────────────────────
elif section == "Teams":
    st.header("Team Referee Bias Analysis")
    bias_data = fetch("/teams/bias", {"season": season}) or []
    df = pd.DataFrame(bias_data)

    if df.empty:
        st.info("No team bias data available yet.")
    else:
        st.subheader("Net Referee Bias per Team")
        fig = px.bar(
            df.sort_values("net_bias", ascending=False),
            x="team_code",
            y="net_bias",
            color="net_bias",
            color_continuous_scale="RdYlGn",
            color_continuous_midpoint=0,
            labels={"net_bias": "Net Bias (errors benefited - harmed)", "team_code": "Team"},
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Home vs. Away Bias Index")
        fig_home = px.scatter(
            df,
            x="team_code",
            y="home_bias_index",
            size=df["games_played"],
            color="home_bias_index",
            color_continuous_scale="RdYlGn",
            color_continuous_midpoint=0,
            hover_data=["team_name", "games_played"],
            labels={"home_bias_index": "Home Bias Index", "team_code": "Team"},
        )
        fig_home.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig_home, use_container_width=True)

        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("Most Benefited Teams")
            st.dataframe(
                df[["team_code", "team_name", "net_bias", "bias_per_game"]].head(10),
                use_container_width=True,
            )
        with col_r:
            st.subheader("Most Harmed Teams")
            st.dataframe(
                df.sort_values("net_bias")[["team_code", "team_name", "net_bias", "bias_per_game"]].head(10),
                use_container_width=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# GAMES
# ─────────────────────────────────────────────────────────────────────────────
elif section == "Games":
    st.header("Game Browser")

    round_filter = st.number_input("Filter by round (0 = all)", min_value=0, max_value=34, value=0)
    params: dict = {"season": season}
    if round_filter > 0:
        params["round"] = round_filter

    games = fetch("/games", params) or []
    df = pd.DataFrame(games)

    if df.empty:
        st.info("No games found. Run ingestion first.")
    else:
        df["score"] = df.apply(
            lambda r: f"{r['home_team_code']} {r.get('home_score','?')} – {r.get('away_score','?')} {r['away_team_code']}",
            axis=1,
        )
        st.dataframe(
            df[["game_code", "round_number", "score", "incident_count", "analysis_complete"]],
            use_container_width=True,
        )

        selected_code = st.selectbox("Inspect game", df["game_code"].tolist())
        report = fetch(f"/games/{selected_code}/incidents", {"season": season})
        if report:
            st.subheader(
                f"{report['home_team']} {report.get('home_score','?')} – "
                f"{report.get('away_score','?')} {report['away_team']}"
            )
            st.write(f"**Referees:** {', '.join(report['referees']) or 'Unknown'}")
            st.write(f"**Total incidents:** {report['total_incidents']}  |  "
                     f"**High/Critical:** {report['high_critical_count']}")

            inc_df = pd.DataFrame(report["incidents"])
            if not inc_df.empty:
                st.dataframe(inc_df, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENTS
# ─────────────────────────────────────────────────────────────────────────────
elif section == "Incidents":
    st.header("Incident Explorer")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        sev_filter = st.selectbox("Severity", ["all", "low", "medium", "high", "critical"])
    with col_f2:
        type_filter = st.selectbox(
            "Type",
            ["all", "wrong_foul_call", "missed_foul", "wrong_violation",
             "missed_violation", "charge_block_error", "out_of_bounds_error",
             "goaltending_error", "other"],
        )
    with col_f3:
        limit = st.number_input("Max results", min_value=10, max_value=500, value=100)

    params = {"season": season, "limit": limit}
    if sev_filter != "all":
        params["severity"] = sev_filter
    if type_filter != "all":
        params["incident_type"] = type_filter

    incidents = fetch("/incidents", params) or []
    df = pd.DataFrame(incidents)

    if df.empty:
        st.info("No incidents match the current filters.")
    else:
        st.metric("Matching incidents", len(df))
        st.dataframe(
            df[[
                "id", "period", "game_clock", "incident_type", "severity",
                "team_benefited", "team_harmed", "ai_confidence", "verification_status",
            ]],
            use_container_width=True,
        )

        # Show detail for a selected incident
        inc_id = st.number_input("Incident ID for detail view", min_value=1, value=int(df["id"].iloc[0]))
        detail = fetch(f"/incidents/{int(inc_id)}")
        if detail:
            st.json(detail)

        # Inline reviewer tool
        st.subheader("Review & Update Incident")
        review_id = st.number_input("Incident ID to review", min_value=1, key="review_id")
        new_status = st.selectbox("New verification status", ["pending", "confirmed", "disputed", "overturned"])
        new_desc = st.text_area("Notes / description")
        if st.button("Save Review"):
            try:
                r = httpx.patch(
                    f"{API_BASE}/incidents/{int(review_id)}",
                    json={"verification_status": new_status, "description": new_desc},
                    timeout=10,
                )
                r.raise_for_status()
                st.success("Incident updated!")
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Update failed: {exc}")
