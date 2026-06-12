# Populates demand_t1..demand_t4 in us_dma.csv and ca_cities.csv using Google
# Trends (via pytrends). Run this on your own machine, inside the project venv:
#
#   pip install pytrends
#   python fetch_demand.py
#
# Terms are queried ONE AT A TIME: multi-term queries make Google return each
# region's percentage split across the terms (sums to ~100 per region), which
# destroys cross-region comparison. Single-term queries return the true 0-100
# index across regions.
#
# Granularity:
#   US     -> Nielsen DMA (matches the map regions directly)
#   Canada -> PROVINCE level. Google Trends does not expose city-level data
#             for Canada (CITY resolution returns provinces), so every city
#             carries its province's index; Quebec cities add the French
#             mirror terms. City differentiation in Canada therefore comes
#             from hardness, income, and population, not demand.
#
# ~128 requests total, roughly 80 minutes at current pacing. Every finished
# request is cached in demand_cache_v2.json: abort and rerun to resume.

import csv
import json
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

try:
    from pytrends.request import TrendReq
except ImportError:
    sys.exit("pytrends is not installed. Run: pip install pytrends")

TIMEFRAME = "today 12-m"
CACHE_FILE = Path("demand_cache_v2.json")

TERMS_EN = {
    "demand_t1": ["shower filter", "filtered shower head", "shower head filter",
                  "water filter for shower", "best shower filter",
                  "shower filter for hard water", "vitamin c shower filter"],
    "demand_t2": ["hard water hair", "hard water skin", "hard water hair loss",
                  "limescale hair", "chlorine hair", "chlorine dry skin",
                  "water softener for shower", "well water hair", "rust in water hair"],
    "demand_t3": ["dry hair", "very dry hair", "dry hair treatment",
                  "shampoo for dry hair", "best shampoo for dry hair", "frizzy hair",
                  "anti frizz products", "dry scalp", "itchy scalp", "flaky scalp",
                  "hair breakage", "brittle hair", "dull hair", "color fading hair",
                  "dry skin", "very dry skin", "best moisturizer for dry skin",
                  "body lotion for dry skin", "itchy skin after shower",
                  "tight skin after shower"],
    "demand_t4": ["the ordinary skincare", "aesop skincare", "cerave",
                  "la roche posay", "niacinamide", "retinol",
                  "hyaluronic acid serum", "vitamin c serum", "skincare routine",
                  "skin barrier repair", "korean skincare", "glass skin",
                  "double cleansing", "salicylic acid cleanser"],
}

TERMS_FR = {
    "demand_t1": ["filtre de douche", "pommeau de douche filtrant",
                  "meilleur filtre de douche"],
    "demand_t2": ["eau dure cheveux", "eau calcaire cheveux", "calcaire cheveux",
                  "chlore cheveux", "adoucisseur d'eau douche"],
    "demand_t3": ["cheveux secs", "shampoing cheveux secs", "cheveux cassants",
                  "cheveux ternes", "frisottis", "cuir chevelu sec",
                  "démangeaisons cuir chevelu", "peau sèche",
                  "meilleure crème hydratante peau sèche",
                  "peau qui tire après la douche"],
    "demand_t4": ["the ordinary", "aesop", "niacinamide", "rétinol",
                  "sérum acide hyaluronique", "sérum vitamine c",
                  "routine soin visage", "barrière cutanée", "soin coréen",
                  "nettoyant acide salicylique"],
}

# Trends DMA spellings that differ from the boundary file (normalised form)
US_ALIASES = {
    "birminghamal": "Birmingham (Anniston and Tuscaloosa), AL",
    "florencemyrtlebeachsc": "Myrtle Beach-Florence, SC",
    "miamiftlauderdalefl": "Miami-Fort Lauderdale, FL",
    "paducahkycapegirardeaumoharrisburgmountvernonil": "Paducah, KY-Cape Girardeau, MO-Harrisburg, IL",
    "wichitahutchinsonks": "Wichita-Hutchinson, KS Plus",
}

PROVINCES = {"ON": "ontario", "QC": "quebec", "BC": "british columbia",
             "AB": "alberta", "MB": "manitoba", "SK": "saskatchewan",
             "NS": "nova scotia", "NB": "new brunswick",
             "NL": "newfoundland and labrador", "PE": "prince edward island"}


def norm(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def norm_tight(s):
    return re.sub(r"[^a-z0-9]", "", norm(s))


cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 30))

ALL_EN = sum(TERMS_EN.values(), [])
ALL_FR = sum(TERMS_FR.values(), [])
TOTAL_REQUESTS = len(ALL_EN) * 2 + len(ALL_FR)
done_requests = 0


def fetch_term(term, geo, resolution):
    """One term per query: returns the true 0-100 index across regions."""
    global done_requests
    key = f"v2|{geo}|{resolution}|{TIMEFRAME}|{term}"
    if key in cache:
        done_requests += 1
        return cache[key]
    for attempt in range(5):
        try:
            pytrends.build_payload([term], timeframe=TIMEFRAME, geo=geo)
            df = pytrends.interest_by_region(resolution=resolution,
                                             inc_low_vol=True, inc_geo_code=False)
            result = {region: int(row.iloc[0]) for region, row in df.iterrows()}

            # Guard against the share-normalisation failure mode.
            nz = [v for v in result.values() if v > 0]
            if len(nz) > 10 and sum(v == 100 for v in nz) / len(nz) > 0.5:
                sys.exit(f"Aborting: '{term}' returned flat 100s across regions, "
                         "which means Google served share data again. Do not "
                         "trust this run; report the issue.")

            cache[key] = result
            CACHE_FILE.write_text(json.dumps(cache))
            done_requests += 1
            time.sleep(random.uniform(25, 40))
            return result
        except SystemExit:
            raise
        except Exception as e:
            wait = 60 * (2 ** attempt)
            print(f"  blocked/error ({e.__class__.__name__}), retrying in {wait}s "
                  f"(progress is cached, safe to abort and rerun later)")
            time.sleep(wait)
    sys.exit("Google kept refusing after 5 attempts. Run the script again "
             "in an hour; it will resume from demand_cache_v2.json.")


def tier_totals(terms, geo, resolution):
    totals = {}
    for term in terms:
        print(f"  [{done_requests + 1}/{TOTAL_REQUESTS}] {geo}/{resolution}: {term}")
        for region, val in fetch_term(term, geo, resolution).items():
            totals[region] = totals.get(region, 0) + val
    return totals


print(f"Single-term mode: {TOTAL_REQUESTS} requests, roughly 80 minutes. "
      "Safe to abort and rerun; finished requests are cached.")

# ---------------- United States ----------------
print("United States: 4 tiers at DMA resolution")
us_rows = list(csv.DictReader(open("us_dma.csv", newline="", encoding="utf-8")))
us_by_norm = {norm_tight(r["dma_name"]): r for r in us_rows}
us_by_name = {r["dma_name"]: r for r in us_rows}

unmatched = set()
for tier, terms in TERMS_EN.items():
    totals = tier_totals(terms, "US", "DMA")
    for region, val in totals.items():
        key = norm_tight(region)
        row = us_by_norm.get(key) or us_by_name.get(US_ALIASES.get(key, ""))
        if row is None:
            unmatched.add(region)
            continue
        row[tier] = val

# ---------------- Canada (province level) ----------------
print("Canada: 4 tiers at province level (Trends has no city data for CA)")
ca_rows = list(csv.DictReader(open("ca_cities.csv", newline="", encoding="utf-8")))

def province_totals_logged(termset, label):
    out = {}
    for tier, terms in termset.items():
        tot = {}
        for term in terms:
            print(f"  [{done_requests + 1}/{TOTAL_REQUESTS}] CA/REGION ({label}): {term}")
            for region, val in fetch_term(term, "CA", "REGION").items():
                tot[norm(region)] = tot.get(norm(region), 0) + val
        out[tier] = tot
    return out

en = province_totals_logged(TERMS_EN, "EN")
print("Quebec: French term mirror")
fr = province_totals_logged(TERMS_FR, "FR")

for r in ca_rows:
    p = PROVINCES[r["province"]]
    for tier in TERMS_EN:
        val = en[tier].get(p, 0)
        if r["french_market"] == "1":
            val += fr[tier].get(p, 0)
        r[tier] = val

# ---------------- write back ----------------
us_cols = ["dma_name", "principal_city", "hardness_mgl", "demand_t1", "demand_t2",
           "demand_t3", "demand_t4", "population", "median_income",
           "hardness_source", "precision_flag"]
with open("us_dma.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=us_cols)
    w.writeheader()
    w.writerows([{k: r.get(k, "") for k in us_cols} for r in us_rows])

ca_cols = ["city", "province", "lat", "lon", "french_market", "hardness_mgl",
           "demand_t1", "demand_t2", "demand_t3", "demand_t4", "population",
           "median_income", "hardness_source", "precision_flag"]
with open("ca_cities.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=ca_cols)
    w.writeheader()
    w.writerows([{k: r.get(k, "") for k in ca_cols} for r in ca_rows])

# ---------------- coverage report ----------------
us_done = sum(1 for r in us_rows if r.get("demand_t1") not in ("", None))
print(f"\nUS: demand written for {us_done}/{len(us_rows)} DMAs")
if unmatched:
    print(f"  Trends regions with no map match (AK/HI markets are expected here): "
          f"{sorted(unmatched)[:8]}")

t1 = [int(r["demand_t1"]) for r in us_rows if r.get("demand_t1") not in ("", None)]
if t1 and len(set(t1)) < 10:
    print("WARNING: demand_t1 has almost no variation; data may be bad.")
else:
    print(f"Gradient check OK: demand_t1 spans {min(t1)}-{max(t1)} "
          f"with {len(set(t1))} distinct values.")
print("Done. Values are Google Trends relative indexes (12 months).")
