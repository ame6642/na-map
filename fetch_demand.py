# Populates demand_t1..demand_t4 in us_dma.csv and ca_cities.csv using Google
# Trends (via pytrends). Run this on your own machine, inside the project venv:
#
#   pip install pytrends
#   python fetch_demand.py
#
# What it does:
#   US     -> interest by Nielsen DMA (matches the map regions directly)
#   Canada -> interest by city, falling back to province where Trends has no
#             city-level data; Quebec cities also get the French term mirror
#
# Values are Google Trends relative indexes (share-of-search, 0-100 per term
# batch), summed per tier. They are comparable across regions in one run but
# are NOT absolute search volumes. The app is configured for this basis.
#
# Google rate-limits aggressively. The script sleeps between requests, retries
# with backoff on 429s, and caches every completed request in
# demand_cache.json, so if it dies partway just run it again and it resumes.

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
CACHE_FILE = Path("demand_cache.json")

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

# Trends city/region name -> ca_cities.csv city name (after normalisation)
CA_ALIASES = {
    "ottawa": "Ottawa-Gatineau", "gatineau": "Ottawa-Gatineau",
    "quebec": "Quebec City", "quebec city": "Quebec City",
    "kitchener": "Kitchener-Waterloo", "waterloo": "Kitchener-Waterloo",
    "cambridge": "Kitchener-Waterloo",
    "st catharines": "St. Catharines-Niagara",
    "niagara falls": "St. Catharines-Niagara",
    "sudbury": "Greater Sudbury", "greater sudbury": "Greater Sudbury",
    "st johns": "St. John's", "saint johns": "St. John's",
    "chicoutimi": "Saguenay", "saguenay": "Saguenay",
    "trois rivieres": "Trois-Rivieres", "montreal": "Montreal",
    "abbotsford": "Abbotsford", "mission": "Abbotsford",
}

PROVINCES = {"ON": "Ontario", "QC": "Quebec", "BC": "British Columbia",
             "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan",
             "NS": "Nova Scotia", "NB": "New Brunswick",
             "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island"}


def norm(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def norm_tight(s):
    return re.sub(r"[^a-z0-9]", "", norm(s))


def batches(terms, size=5):
    return [terms[i:i + size] for i in range(0, len(terms), size)]


cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 30))


def fetch(batch, geo, resolution):
    key = f"{geo}|{resolution}|{TIMEFRAME}|" + "|".join(batch)
    if key in cache:
        return cache[key]
    for attempt in range(5):
        try:
            pytrends.build_payload(batch, timeframe=TIMEFRAME, geo=geo)
            df = pytrends.interest_by_region(resolution=resolution,
                                             inc_low_vol=True, inc_geo_code=False)
            result = {region: int(row.sum()) for region, row in df.iterrows()}
            cache[key] = result
            CACHE_FILE.write_text(json.dumps(cache))
            time.sleep(random.uniform(10, 18))
            return result
        except Exception as e:
            wait = 60 * (2 ** attempt)
            print(f"  blocked/error ({e.__class__.__name__}), retrying in {wait}s "
                  f"(progress is cached, safe to abort and rerun later)")
            time.sleep(wait)
    sys.exit("Google kept refusing after 5 attempts. Run the script again "
             "in an hour; it will resume from demand_cache.json.")


def tier_totals(terms, geo, resolution):
    totals = {}
    for b in batches(terms):
        print(f"  {geo}/{resolution}: {b[0]} (+{len(b)-1} terms)")
        for region, val in fetch(b, geo, resolution).items():
            totals[region] = totals.get(region, 0) + val
    return totals


# ---------------- United States ----------------
print("United States: 4 tiers at DMA resolution")
us_rows = list(csv.DictReader(open("us_dma.csv", newline="", encoding="utf-8")))
us_by_norm = {norm_tight(r["dma_name"]): r for r in us_rows}

unmatched = set()
for tier, terms in TERMS_EN.items():
    totals = tier_totals(terms, "US", "DMA")
    for region, val in totals.items():
        row = us_by_norm.get(norm_tight(region))
        if row is None:
            unmatched.add(region)
            continue
        row[tier] = val

# ---------------- Canada ----------------
print("Canada: 4 tiers, city level with province fallback")
ca_rows = list(csv.DictReader(open("ca_cities.csv", newline="", encoding="utf-8")))

def match_city(region_name):
    n = norm(region_name)
    if n in CA_ALIASES:
        return CA_ALIASES[n]
    for r in ca_rows:
        if norm(r["city"]) == n:
            return r["city"]
    return None

for tier, terms in TERMS_EN.items():
    city_vals = tier_totals(terms, "CA", "CITY")
    prov_vals = tier_totals(terms, "CA", "REGION")
    resolved = {}
    for region, val in city_vals.items():
        city = match_city(region)
        if city:
            resolved[city] = max(resolved.get(city, 0), val)
    for r in ca_rows:
        if r["city"] in resolved:
            r[tier] = resolved[r["city"]]
            r.setdefault("_basis", set()).add("city")
        else:
            pv = prov_vals.get(PROVINCES[r["province"]], 0)
            r[tier] = pv
            r.setdefault("_basis", set()).add("province")

print("Quebec: French term mirror, added to Quebec cities")
for tier, terms in TERMS_FR.items():
    city_vals = tier_totals(terms, "CA", "CITY")
    prov_vals = tier_totals(terms, "CA", "REGION")
    resolved = {}
    for region, val in city_vals.items():
        city = match_city(region)
        if city:
            resolved[city] = max(resolved.get(city, 0), val)
    for r in ca_rows:
        if r["french_market"] == "1":
            extra = resolved.get(r["city"], prov_vals.get(PROVINCES[r["province"]], 0))
            r[tier] = int(r[tier] or 0) + extra

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
us_done = sum(1 for r in us_rows if r.get("demand_t1"))
print(f"\nUS: demand written for {us_done}/{len(us_rows)} DMAs")
if unmatched:
    print(f"  Trends regions with no map match (ignored): {sorted(unmatched)[:8]}")
city_n = sum(1 for r in ca_rows if "city" in r.get("_basis", set()))
print(f"Canada: {city_n} cities at city-level data, "
      f"{len(ca_rows) - city_n} using province fallback")
print("Done. Demand values are Google Trends relative indexes (12 months).")
