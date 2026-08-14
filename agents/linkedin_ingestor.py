#!/usr/bin/env python3
"""
linkedin_ingestor.py

Active LinkedIn job search via public endpoint (no API key).
Output: data/raw_jobs/linkedin_{data}.json
"""

import os
import json
import re
import time
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any

SEARCH_QUERIES = [
    # Zurich
    ("Data Analyst Intern", "Zurich, Switzerland"),
    ("Business Analyst Intern", "Zurich, Switzerland"),
    ("Data Science Intern", "Zurich, Switzerland"),
    ("AI Intern", "Zurich, Switzerland"),
    ("AI Agent", "Zurich, Switzerland"),
    ("Analytics Intern", "Zurich, Switzerland"),
    ("Junior Data Analyst", "Zurich, Switzerland"),
    ("Working Student Data", "Zurich, Switzerland"),
    ("Praktikum Data", "Zurich, Switzerland"),
    # Zug
    ("Data Analyst Intern", "Zug, Switzerland"),
    ("Business Analyst Intern", "Zug, Switzerland"),
    ("Praktikum Business", "Zug, Switzerland"),
    # Basel / Winterthur / Bern (nearby region)
    ("Data Intern", "Basel, Switzerland"),
    ("Werkstudent Data", "Winterthur, Switzerland"),
]

LINKEDIN_BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def fetch_linkedin_jobs(keywords: str, location: str, start: int = 0) -> List[Dict[str, Any]]:
    params = {
        "keywords": keywords,
        "location": location,
        "start": str(start),
        "f_TPR": "r86400",  # last 24h
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(LINKEDIN_BASE, headers=headers, params=params)
        response.raise_for_status()
        html = response.text
        return parse_jobs_html(html)
    except httpx.HTTPStatusError as e:
        print(f"  [X] HTTP {e.response.status_code} for '{keywords}' in {location}")
        return []
    except Exception as e:
        print(f"  [X] Error: {e}")
        return []


def parse_jobs_html(html: str) -> List[Dict[str, Any]]:
    """Parses the HTML returned by LinkedIn and extracts jobs."""
    jobs = []
    # Each job comes in an <li> with class base-search-result
    job_blocks = re.findall(r'<li[^>]*class="base-search-result__info"[^>]*>(.*?)</li>', html, re.DOTALL)

    for block in job_blocks:
        job = {}

        # Title
        title_match = re.search(r'class="base-search-result__title"[^>]*>.*?<span[^>]*>(.*?)</span>', block, re.DOTALL)
        job["title"] = clean_html(title_match.group(1)) if title_match else "Unknown"

        # Company
        company_match = re.search(r'class="base-search-result__subtitle"[^>]*>.*?<span[^>]*>(.*?)</span>', block, re.DOTALL)
        job["company"] = clean_html(company_match.group(1)) if company_match else "Unknown"

        # Location
        loc_match = re.search(r'class="job-search-card__location"[^>]*>(.*?)</span>', block, re.DOTALL)
        if not loc_match:
            loc_match = re.search(r'class="base-search-result__metadata"[^>]*>.*?<span[^>]*>(.*?)</span>', block, re.DOTALL)
        job["location"] = clean_html(loc_match.group(1)) if loc_match else "Unknown"

        # URL
        url_match = re.search(r'href="(/jobs/view/[^"]+)"', block)
        if url_match:
            job["url"] = "https://www.linkedin.com" + url_match.group(1).split("?")[0]
        else:
            job["url"] = ""

        # Job ID (from URL)
        id_match = re.search(r'/jobs/view/(\d+)', job.get("url", ""))
        job["linkedin_id"] = id_match.group(1) if id_match else ""

        job["portal"] = "linkedin"
        job["description"] = ""  # requires an extra fetch; left empty for now
        job["posted_at"] = datetime.now(timezone.utc).isoformat()

        if job["title"] != "Unknown":
            jobs.append(job)

    return jobs


def clean_html(raw: str) -> str:
    """Removes HTML tags and entities."""
    text = re.sub(r'<[^>]+>', '', raw)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.strip()
    return text


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
    filepath = f"data/raw_jobs/linkedin_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    return filepath


def main():
    print("=" * 70)
    print("LINKEDIN -- Active job search")
    print("=" * 70)

    all_jobs = []
    for keywords, location in SEARCH_QUERIES:
        jobs = fetch_linkedin_jobs(keywords, location)
        print(f"  > {keywords[:30]:30} in {location[:25]:25} -> {len(jobs):2} jobs")
        all_jobs.extend(jobs)
        time.sleep(2)

    if not all_jobs:
        print("\n[!] No jobs found on LinkedIn.")
        return None

    unique = deduplicate(all_jobs)
    print(f"\n[stats] Raw total: {len(all_jobs)} | Unique: {len(unique)}")
    filepath = save(unique)

    print(f"[saved] {filepath}")
    print("\nTop 5:")
    for i, job in enumerate(unique[:5], 1):
        print(f"   {i}. [{job['company']}] {job['title']} ({job['location']})")
    print("[OK] LinkedIn done")
    return filepath


if __name__ == "__main__":
    main()
