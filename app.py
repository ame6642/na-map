import json
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Shower Filter Acquisition Map: North America", layout="wide")

# Demand columns hold Google Trends relative indexes (share-of-search, already
# population-adjusted by Google). If you ever replace them with Keyword Planner
# absolute volumes, set this to False and the basis toggle reverts to the
# guide's original per-capita / absolute logic.
DEMAND_IS_TRENDS_INDEX = True

NUM_COLS = ["hardness_mgl", "demand_t1", "demand_t2", "demand_t3", "demand_t4",
            "population", "median_income"]

LABELS = {
    "dma_name": "Market (DMA)",
    "city": "City",
    "hardness_mgl": "Water hardness (mg/L)",
    "demand_t1": "Solution-aware searches",
    "demand_t2": "Problem-aware searches",
    "demand_t3": "Symptom searches",
    "demand_t4": "Beauty engagement searches",
    "population": "Population",
    "median_income": "Median household income",
    "score": "Opportunity score",
    "quality": "Hardness data quality",
}

QUALITY = {"precise": "Verified (utility report)", "approximate": "Estimate"}

@st.cache_data
def load_geo():
    with open("us_dma.geojson", encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def load_csv(path):
    df = pd.read_csv(path)
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["quality"] = df["precision_flag"].map(QUALITY).fillna("No data yet")
    return df

def norm(s):
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or hi == lo:
        return s * 0
    return (s - lo) / (hi - lo)

# ---------------- sidebar ----------------
st.sidebar.title("Controls")
country = st.sidebar.radio("Country", ["United States", "Canada"])

preset = st.sidebar.radio("View", [
    "Blended",
    "Hard water only",
    "Search demand only",
    "Unaware audience (symptoms + beauty engagement + hard water)",
])

if DEMAND_IS_TRENDS_INDEX:
    demand_mode = st.sidebar.radio(
        "Demand basis",
        ["Search intensity (per capita)", "Estimated audience (intensity x population)"],
        help="Google Trends indexes are share-of-search, so they are already "
             "population-adjusted. Intensity shows unusual concentration; "
             "estimated audience scales by population to show market size.")
    per_capita = demand_mode.startswith("Search intensity")
else:
    demand_mode = st.sidebar.radio("Demand basis", ["Per 100k residents", "Absolute volume"])
    per_capita = demand_mode.startswith("Per 100k")

if preset == "Blended":
    w_hard = st.sidebar.slider("Water hardness", 0, 100, 30)
    w_t1 = st.sidebar.slider("Tier 1: solution-aware searches", 0, 100, 10)
    w_t2 = st.sidebar.slider("Tier 2: problem-aware searches", 0, 100, 20)
    w_t3 = st.sidebar.slider("Tier 3: symptom searches", 0, 100, 20)
    w_t4 = st.sidebar.slider("Tier 4: beauty engagement searches", 0, 100, 10)
    w_inc = st.sidebar.slider("Household income", 0, 100, 10)
elif preset == "Hard water only":
    w_hard, w_t1, w_t2, w_t3, w_t4, w_inc = 100, 0, 0, 0, 0, 0
elif preset == "Search demand only":
    w_hard, w_inc = 0, 0
    w_t1 = st.sidebar.slider("Tier 1: solution-aware searches", 0, 100, 25)
    w_t2 = st.sidebar.slider("Tier 2: problem-aware searches", 0, 100, 25)
    w_t3 = st.sidebar.slider("Tier 3: symptom searches", 0, 100, 25)
    w_t4 = st.sidebar.slider("Tier 4: beauty engagement searches", 0, 100, 25)
else:  # Unaware audience
    w_hard, w_t1, w_t2, w_t3, w_t4, w_inc = 40, 0, 0, 35, 25, 0

total = w_hard + w_t1 + w_t2 + w_t3 + w_t4 + w_inc
if total == 0:
    st.warning("Set at least one weight above zero.")
    st.stop()

# ---------------- data and score ----------------
df = load_csv("us_dma.csv" if country == "United States" else "ca_cities.csv").copy()

TIERS = ["demand_t1", "demand_t2", "demand_t3", "demand_t4"]
for t in TIERS:
    if DEMAND_IS_TRENDS_INDEX:
        df[t + "_basis"] = df[t] if per_capita else df[t] * df["population"] / 100_000
    else:
        df[t + "_basis"] = df[t] / df["population"] * 100_000 if per_capita else df[t]

df["score"] = (
    (w_hard / total) * norm(df["hardness_mgl"]).fillna(0)
    + (w_t1 / total) * norm(df["demand_t1_basis"]).fillna(0)
    + (w_t2 / total) * norm(df["demand_t2_basis"]).fillna(0)
    + (w_t3 / total) * norm(df["demand_t3_basis"]).fillna(0)
    + (w_t4 / total) * norm(df["demand_t4_basis"]).fillna(0)
    + (w_inc / total) * norm(df["median_income"]).fillna(0)
)

# ---------------- map ----------------
st.title("Shower Filter Acquisition Opportunity: " + country)

HOVER = {"hardness_mgl": ":.0f", "demand_t1": ":,.0f", "demand_t2": ":,.0f",
         "demand_t3": ":,.0f", "demand_t4": ":,.0f", "population": ":,.0f",
         "median_income": ":$,.0f", "score": ":.2f", "quality": True}

if country == "United States":
    fig = px.choropleth(
        df, geojson=load_geo(), locations="dma_name",
        featureidkey="properties.dma1", color="score",
        color_continuous_scale=["#F6F1E8", "#C9B69C", "#8F7A5E", "#26211B"],
        hover_data=HOVER, labels=LABELS, scope="usa",
    )
    fig.update_geos(fitbounds="locations", visible=False)
else:
    plot_df = df.dropna(subset=["score"]).copy()
    plot_df["bubble"] = plot_df["population"].fillna(plot_df["population"].median())
    fig = px.scatter_geo(
        plot_df, lat="lat", lon="lon", size="bubble", color="score",
        color_continuous_scale=["#F6F1E8", "#C9B69C", "#8F7A5E", "#26211B"],
        hover_name="city",
        hover_data={**HOVER, "lat": False, "lon": False, "bubble": False},
        labels=LABELS, scope="north america", size_max=42,
    )
    fig.update_geos(lataxis_range=[41, 62], lonaxis_range=[-132, -52],
                    showcountries=True, countrycolor="#C9B69C")

fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0},
                  coloraxis_colorbar_title="Opportunity")
st.plotly_chart(fig, width="stretch")

st.caption(
    "Search demand is a Google Trends relative index (12-month share-of-search "
    "by region, four awareness tiers, summed per tier; Quebec includes "
    "French-language terms). Indexes compare regions directionally and become "
    "absolute volumes when re-run through an active Google Ads account. Water "
    "hardness is mg/L as CaCO3, marked per region as a verified utility figure "
    "or an estimate. Income is shown in local currency (USD / CAD)."
)

# ---------------- ranked table ----------------
st.subheader("Regions ranked by opportunity")
name_col = "dma_name" if country == "United States" else "city"
table = (df.sort_values("score", ascending=False)
           [[name_col, "hardness_mgl", "demand_t1", "demand_t2", "demand_t3",
             "demand_t4", "population", "median_income", "score", "quality"]]
           .rename(columns=LABELS))
st.dataframe(
    table,
    width="stretch", hide_index=True,
    column_config={
        LABELS["hardness_mgl"]: st.column_config.NumberColumn(format="%.0f"),
        LABELS["demand_t1"]: st.column_config.NumberColumn(format="localized"),
        LABELS["demand_t2"]: st.column_config.NumberColumn(format="localized"),
        LABELS["demand_t3"]: st.column_config.NumberColumn(format="localized"),
        LABELS["demand_t4"]: st.column_config.NumberColumn(format="localized"),
        LABELS["population"]: st.column_config.NumberColumn(format="localized"),
        LABELS["median_income"]: st.column_config.NumberColumn(format="dollar"),
        LABELS["score"]: st.column_config.NumberColumn(format="%.3f"),
    },
)

# ---------------- references ----------------
with st.expander("Data sources and methodology"):
    st.markdown(
        "**Method.** Each region is scored 0-1 on a weighted blend of "
        "min-max normalised signals: verified water hardness, four tiers of "
        "search demand (solution-aware, problem-aware, symptom-only, beauty "
        "engagement), and median household income, with population used for "
        "audience scaling. Weights are set in the sidebar.\n\n"
        "**Core datasets**\n"
        "- Market geometry: [Nielsen DMA boundaries](https://github.com/simzou/nielsen-dma)\n"
        "- US population: [Nielsen 2024-25 Local Television Market Universe "
        "Estimates](https://nationalmediaspots.com/DMA-Ranks.pdf) (TV households x 2.5)\n"
        "- US income: [US Census ACS, table S1901](https://data.census.gov/) "
        "(2023 metro medians, rounded)\n"
        "- Canada population and income: [StatCan 2021 Census "
        "Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E)\n"
        "- Search demand: [Google Trends](https://trends.google.com/) relative "
        "indexes, 12 months, by US DMA and Canadian city/province\n"
        "- State-level hardness fallback: [USGS-based state "
        "ranges](https://www.stone-stream.com/blogs/knowledgebase/hard-water-map)\n\n"
        "**Water hardness references by region** (utility and municipal "
        "reports where published; rows marked Estimate use state or "
        "aggregated data pending a utility figure):"
    )
    us_all = load_csv("us_dma.csv")
    ca_all = load_csv("ca_cities.csv")
    refs = {}
    for frame, col in ((us_all, "dma_name"), (ca_all, "city")):
        for _, r in frame.iterrows():
            src = r.get("hardness_source")
            if isinstance(src, str) and src.startswith("http"):
                refs.setdefault(src, []).append(str(r[col]))
    lines = []
    for src in sorted(refs, key=lambda s: -len(refs[s])):
        regions = refs[src]
        host = urlparse(src).netloc.replace("www.", "")
        scope = (", ".join(regions) if len(regions) <= 3
                 else f"{len(regions)} regions")
        lines.append(f"- [{host}]({src}): {scope}")
    st.markdown("\n".join(lines))
