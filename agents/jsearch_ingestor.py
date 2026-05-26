#!/usr/bin/env python3
"""
jsearch_ingestor.py

Busca ativa de vagas via JSearch API (RapidAPI).
Saida: data/raw_jobs/jsearch_{data}.json
"""

import os
import json
import httpx
from datetime import datetime
from typing import List, Dict, Any

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "jsearch.p.rapidapi.com"

SEARCH_QUERIES = [
    "Data Analyst in Zurich, Switzerland",
    "Business Analyst in Zurich, Switzerland",
    "Data Analyst in Zug, Switzerland",
    "Business Analyst in Zug, Switzerland",
    "Analytics Associate in Zurich, Switzerland",
]


def fetch_jsearch(query: str, page: int = 1) -> List[Dict[str, Any]]:
    if not RAPIDAPI_KEY:
        print("  ⚠️  RAPIDAPI_KEY nao configurada. Pulando JSearch.")
        return []

    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }
    params = {
        "query": query,
        "page": str(page),
        "num_pages": "1",
        "date_posted": "today",
        "employment_types": "FULLTIME",
        "job_requirements": "no_experience",
        "remote_jobs_only": "false",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
        jobs = data.get("data", [])
        print(f"  🔍 {query[:45]:45} → {len(jobs):2} vagas")
        return jobs
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = e.response.text[:500]
        if status == 429:
            print(f"  ⚠️  Rate limit.")
        elif status == 401:
            print(f"  ❌ API Key invalida.")
        else:
            print(f"  ❌ HTTP {status}: {body}")
        return []
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return []


def normalize_job(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "portal": "jsearch",
        "title": raw.get("job_title", "Unknown"),
        "company": raw.get("employer_name", "Unknown"),
        "location": f"{raw.get('job_city', '')}, {raw.get('job_country', '')}".strip(", "),
        "description": raw.get("job_description", "")[:4000],
        "url": raw.get("job_apply_link", raw.get("job_google_link", "")),
        "posted_at": raw.get("job_posted_at_datetime_utc", datetime.now().isoformat()),
        "salary_min": raw.get("job_min_salary"),
        "salary_max": raw.get("job_max_salary"),
        "salary_currency": raw.get("job_salary_currency", "CHF"),
        "is_remote": raw.get("job_is_remote", False),
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
    filepath = f"data/raw_jobs/jsearch_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    return filepath


def main():
    print("=" * 70)
    print("🔍 JSEARCH — Busca ativa de vagas")
    print("=" * 70)

    all_raw = []
    for query in SEARCH_QUERIES:
        jobs = fetch_jsearch(query)
        all_raw.extend(jobs)

    if not all_raw:
        print("\n⚠️  Nenhuma vaga. Verifique RAPIDAPI_KEY.")
        return None

    normalized = [normalize_job(j) for j in all_raw]
    unique = deduplicate(normalized)

    print(f"\n📊 Total bruto: {len(all_raw)} | Unicas: {len(unique)}")
    filepath = save(unique)

    print(f"💾 Salvo: {filepath}")
    print("\n🏆 Top 5:")
    for i, job in enumerate(unique[:5], 1):
        print(f"   {i}. [{job['company']}] {job['title']}")
    print("✅ JSearch concluido")
    return filepath


if __name__ == "__main__":
    main()
