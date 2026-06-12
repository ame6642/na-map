# NA Acquisition Heatmap (na-map)

Interactive North America acquisition map for the shower filter category: US choropleth by Nielsen DMA, Canada by city, scored on water hardness, four tiers of search demand, income, and population. Brand-neutral throughout.

## Run it locally

In VS Code, open this folder, then Terminal > New Terminal:

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, answer Y, then retry the activate line.

## Filling the demand columns (one command)

Demand uses Google Trends relative indexes instead of manual Keyword Planner lookups. With the venv active:

```
python fetch_demand.py
```

It pulls all four term tiers for every US DMA and every Canadian province (Google Trends does not expose city-level data for Canada, so each city carries its province's index), adds the French mirror for Quebec, and writes the results into the two CSVs. Terms are queried one at a time; multi-term queries make Google return per-region shares instead of the cross-region index, which flattens the map. Google rate-limits scrapers, so the script sleeps between requests and caches finished requests in `demand_cache_v2.json`; if it stalls or you abort, run it again and it resumes. Roughly 80 minutes for a full fresh run; refreshes that reuse the cache are instant.

Trends indexes are share-of-search, already population-adjusted. The app accounts for this: "Search intensity" uses the index directly, "Estimated audience" multiplies by population. If you later replace these with true Keyword Planner volumes, set `DEMAND_IS_TRENDS_INDEX = False` at the top of `app.py`.

## Data status

- **Hardness**: 206/206 US DMAs and 35/35 Canadian cities. Each row carries a source URL and a flag: `precise` (published utility figure) or `approximate` (state-level USGS-based range midpoint or aggregated data). The app surfaces this as a "Hardness data quality" column and lists every source as a hyperlink under "Data sources and methodology".
- **Population**: US = Nielsen 2024-25 TV households x 2.5; Canada = StatCan 2021 census.
- **Income**: US = ACS 2023 metro medians (rounded, refresh from data.census.gov table S1901 when convenient); Canada = StatCan 2021 census (2020 income, CAD).
- **Demand**: blank until you run `fetch_demand.py`.

## Files

`app.py` (the app), `us_dma.csv` + `ca_cities.csv` (data), `us_dma.geojson` (boundaries), `fetch_demand.py` (demand fill), `requirements.txt`. Local-only helpers: `convert.py`, `make_tables.py`, `fill_data.py`, `backfill_hardness.py`, `nielsentopo.json`.

## Deploy / update the live app

The repo deploys on Streamlit Community Cloud (share.streamlit.io) from `app.py`. After running `fetch_demand.py`, upload the refreshed `us_dma.csv` and `ca_cities.csv` to the GitHub repo and the live app updates automatically.
