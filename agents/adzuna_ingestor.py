#!/usr/bin/env python3
"""
adzuna_ingestor.py

Active job search via the Adzuna API (official, free up to 100 calls/day).
Covers Switzerland (country=ch) and all of Europe.
Output: data/raw_jobs/adzuna_{date}.json

Docs: https://developer.adzuna.com/
"""

import os
import json
import httpx
from datetime import datetime
from typing import List, Dict, Any
from urllib.parse import urlsplit

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/ch/search/1"
ADZUNA_MAX_HITS = int(os.environ.get("ADZUNA_MAX_HITS", "35"))
# Radius in km around each `where`. 30 reaches Zug and Winterthur from Zurich.
ADZUNA_DISTANCE_KM = int(os.environ.get("ADZUNA_DISTANCE_KM", "30"))

# Search targeting. Adzuna's free tier allows 100 calls/day, and this list is
# multiplied by len(LOCATIONS) and by the number of scheduled runs (2):
# 18 queries x 1 location -> 36 calls/day, leaving room for the up to 24 that
# agents/description_enricher.py may spend. Redo that arithmetic before
# adding a query or a location.
#
# Why one location now (measured 2026-08-23 over 84 days of data/raw_jobs/):
# the search ran against Zurich AND Zug, and Zug returned 4 DISTINCT jobs in
# those 84 days while eating half the daily quota -- about 2,000 calls for
# four postings. Zug is 30 km from Zurich, so ADZUNA_DISTANCE_KM covers it
# from the Zurich search in the same call. The freed budget went into more
# queries instead. If Zug postings stop appearing, that radius is the first
# thing to check.
#
# Aimed at what the CV actually asks for: "seeking a new internship to deepen
# my expertise in agentic systems and data platform engineering". So the mix
# is internship/working-student first and junior second, across the two
# themes (AI/agentic and data platform), plus automation, which is his
# current job title. English and German both, because Swiss postings split
# roughly evenly between "Internship" and "Praktikum/Werkstudent".
#
# Deliberately NOT here: mid-level "Senior/Lead" phrasing, and pure software
# engineering, which the scoring prompt auto-SKIPs anyway.
#
# Override without touching code: ADZUNA_QUERIES="AI Engineer;Data Engineer"
_DEFAULT_QUERIES = [
    "AI Engineer Intern",
    "Junior AI Engineer",
    "Praktikum AI",
    "Werkstudent AI",
    "Machine Learning Intern",
    "Data Engineer Intern",
    "Junior Data Engineer",
    "Data Platform Engineer",
    "Praktikum Data Engineering",
    "Werkstudent Data",
    "Junior Automation Engineer",
    "Praktikum Automation",
    # Added 2026-08-23 with the budget freed by dropping the Zug pass. These
    # are shorter on purpose: Adzuna ranks by relevance across the whole
    # posting, so a three-word phrase like "Praktikum Data Engineering" is a
    # much narrower net than the two themes it is made of. Every phrase below
    # is taken from titles the search ACTUALLY returned in the 84 days of
    # history, not invented: "agentic", "applied AI", "founding engineer" and
    # the bare "Internship"/"Praktikum" forms account for most of what came
    # through, and none of them matched any of the twelve queries above.
    "AI Engineer",
    "Agentic AI",
    "Applied AI",
    "Data Scientist Intern",
    "Internship Data",
    "Praktikum Data Science",
]
SEARCH_QUERIES = [q.strip() for q in os.environ.get("ADZUNA_QUERIES", "").split(";")
                  if q.strip()] or _DEFAULT_QUERIES
# Overridable the same way, for the same reason.
LOCATIONS = [w.strip() for w in os.environ.get("ADZUNA_LOCATIONS", "").split(";")
             if w.strip()] or ["Zurich"]


def fetch_adzuna(what: str, where: str = "Zurich", max_days_old: int = 7,
                 distance_km: int = None) -> List[Dict[str, Any]]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ⚠️  ADZUNA_APP_ID or ADZUNA_APP_KEY not set. Skipping Adzuna.")
        return []

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        # Adzuna caps this at 50. It costs the same one call either way, so
        # there is no reason to leave results on the table.
        "results_per_page": "50",
        "what": what,
        "where": where,
        # Adzuna defaults to a 5 km radius, which excludes Zug, Winterthur and
        # Baden from a Zurich search. Widening it is free -- still one call.
        "distance": str(ADZUNA_DISTANCE_KM if distance_km is None else distance_km),
        "max_days_old": str(max_days_old),
        "content-type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ADZUNA_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        print(f"  🔍 {what[:40]:40} in {where[:15]:15} → {len(results):2} jobs")
        return results

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = e.response.text[:500]
        if status == 401:
            print(f"  ❌ Invalid App ID/Key.")
        elif status == 429:
            print(f"  ⚠️  Adzuna rate limit hit.")
        else:
            print(f"  ❌ HTTP {status}: {body}")
        return []
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []


def normalize_job(raw: Dict[str, Any]) -> Dict[str, Any]:
    company = raw.get("company", {}) or {}
    location = raw.get("location", {}) or {}
    loc_display = location.get("display_name", "")

    # Strip tracking params: Adzuna embeds our app_id (half of the credential
    # pair) as utm_source in redirect_url -- do not persist it.
    url = raw.get("redirect_url", raw.get("url", ""))
    if url:
        url = urlsplit(url)._replace(query="").geturl()

    return {
        "portal": "adzuna",
        "title": raw.get("title", "Unknown"),
        "company": company.get("display_name", "Unknown") if isinstance(company, dict) else str(company),
        "location": loc_display,
        "description": raw.get("description", "")[:4000],
        "url": url,
        "posted_at": raw.get("created_at", datetime.now().isoformat()),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_currency": raw.get("salary_currency", "CHF"),
        "contract_type": raw.get("contract_type", ""),
        "category": raw.get("category", {}).get("tag", ""),
    }


import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utils import deduplicate_jobs, ensure_dir


def save(jobs: List[Dict[str, Any]]) -> str:
    ensure_dir("data/raw_jobs")
    filepath = f"data/raw_jobs/adzuna_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    return filepath


def main():
    print("=" * 70)
    print("🔍 ADZUNA — Active job search (Switzerland)")
    print("=" * 70)

    all_raw = []
    hit_count = 0
    # One location, wide radius -- see the quota note above LOCATIONS.
    locations = LOCATIONS

    for what in SEARCH_QUERIES:
        if hit_count >= ADZUNA_MAX_HITS:
            print(f"  Quota limit reached, stopping.")
            break
        for where in locations:
            if hit_count >= ADZUNA_MAX_HITS:
                break
            jobs = fetch_adzuna(what, where, max_days_old=7)
            hit_count += 1
            all_raw.extend(jobs)

    if not all_raw:
        print("\n⚠️  No jobs found. Check ADZUNA_APP_ID and ADZUNA_APP_KEY.")
        return None

    normalized = [normalize_job(j) for j in all_raw]
    unique = deduplicate_jobs(normalized)

    print(f"\n📊 Raw: {len(all_raw)} | Unique: {len(unique)}")
    filepath = save(unique)

    print(f"💾 Saved: {filepath}")
    print("\n🏆 Top 5:")
    for i, job in enumerate(unique[:5], 1):
        print(f"   {i}. [{job['company']}] {job['title']} ({job['location']})")
    print("✅ Adzuna done")
    return filepath


if __name__ == "__main__":
    main()
