#!/usr/bin/env python3
"""
adzuna_ingestor.py

Busca ativa de vagas via Adzuna API (oficial, gratuita ate 100 calls/dia).
Cobre a Suica (country=ch) e toda a Europa.
Saida: data/raw_jobs/adzuna_{data}.json

Docs: https://developer.adzuna.com/
"""

import os
import json
import httpx
from datetime import datetime
from typing import List, Dict, Any

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/ch/search/1"
ADZUNA_MAX_HITS = int(os.environ.get("ADZUNA_MAX_HITS", "35"))

SEARCH_QUERIES = [
    "Data Analyst Intern",
    "Business Analyst Intern",
    "Data Science Intern",
    "AI Intern",
    "AI Agent",
    "Analytics Intern",
    "Junior Data Analyst",
    "Working Student Data",
    "Praktikum Data",
    "Praktikum Business",
    "Data Intern",
    "Werkstudent Data",
]


def fetch_adzuna(what: str, where: str = "Zurich", max_days_old: int = 7) -> List[Dict[str, Any]]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ⚠️  ADZUNA_APP_ID or ADZUNA_APP_KEY not set. Skipping Adzuna.")
        return []

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": "20",
        "what": what,
        "where": where,
        "max_days_old": str(max_days_old),
        "content-type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ADZUNA_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        print(f"  🔍 {what[:40]:40} em {where[:15]:15} → {len(results):2} vagas")
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
    
    return {
        "portal": "adzuna",
        "title": raw.get("title", "Unknown"),
        "company": company.get("display_name", "Unknown") if isinstance(company, dict) else str(company),
        "location": loc_display,
        "description": raw.get("description", "")[:4000],
        "url": raw.get("redirect_url", raw.get("url", "")),
        "posted_at": raw.get("created_at", datetime.now().isoformat()),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_currency": raw.get("salary_currency", "CHF"),
        "contract_type": raw.get("contract_type", ""),
        "category": raw.get("category", {}).get("tag", ""),
    }


def deduplicate(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for job in jobs:
        key = (job["company"].lower().strip(), job["title"].lower().strip(), job["location"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def save(jobs: List[Dict[str, Any]]) -> str:
    os.makedirs("data/raw_jobs", exist_ok=True)
    filepath = f"data/raw_jobs/adzuna_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    return filepath


def main():
    print("=" * 70)
    print("🔍 ADZUNA — Busca ativa de vagas (Suica)")
    print("=" * 70)

    all_raw = []
    hit_count = 0
    locations = ["Zurich", "Zug"]

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
    unique = deduplicate(normalized)

    print(f"\n📊 Raw: {len(all_raw)} | Unique: {len(unique)}")
    filepath = save(unique)

    print(f"💾 Salvo: {filepath}")
    print("\n🏆 Top 5:")
    for i, job in enumerate(unique[:5], 1):
        print(f"   {i}. [{job['company']}] {job['title']} ({job['location']})")
    print("✅ Adzuna done")
    return filepath


if __name__ == "__main__":
    main()
