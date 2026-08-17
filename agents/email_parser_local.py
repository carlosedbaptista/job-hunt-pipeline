#!/usr/bin/env python3
"""
email_parser_local.py -- Parse job alert emails using regex + BeautifulSoup.
No API calls. Faster and free.
"""
import json
import os
import re
from typing import List, Dict, Any

from bs4 import BeautifulSoup

# Glassdoor/LinkedIn job-alert cards wrap the whole card (rating, salary
# estimate, apply CTA, "posted N ago" freshness label) in a single <a>,
# so get_text() pulls all of it in as one blob. The freshness/CTA suffix
# changes on every re-send of the same listing (e.g. "1T" -> "2T" -> "3T"),
# which was silently defeating deduplicator.make_hash() -- the same job
# kept re-entering the pipeline as "new" and getting re-evaluated by Kimi.
# Patterns below are stripped before a card's text is used as title/company,
# derived from real polluted rows found in tracker/jobs.db (Climeworks,
# Tethys Robotics, Unisers, Alpine Technology and others all hit this).
_NOISE_PATTERNS = [
    r"\d\.\d\s*★",                                    # rating, e.g. "3.6 ★"
    r"CHF\s*[\d.,’']+\s*-\s*CHF\s*[\d.,’']+\s*\(Arbeitgeber-Schätz\.?\)",  # salary estimate
    r"Schnell bewerben",
    r"Jetzt bewerben",
    r"Quick apply",
    r"Gerade gepostet",
    r"Actively recruiting",
    r"vor \d+\s*(?:Tag|Stunde|Woche)[en]?",
    r"\d+\s*(?:T|Std|h|d)\b\s*$",                          # trailing "1T" / "13Std" freshness suffix -- no \b
                                                            # before \d+: it's glued to the CTA text with no
                                                            # separator ("bewerben1T"), so letter->digit is not
                                                            # a word boundary and \b would never match there
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


def _strip_scraped_noise(text: str) -> str:
    """Removes known job-alert UI noise (rating, salary badge, apply CTA,
    freshness label) from scraped card text -- see _NOISE_PATTERNS."""
    cleaned = _NOISE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_html_emails(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract job listings from HTML email bodies using regex + BeautifulSoup."""
    jobs = []
    job_keywords = [
        "analyst", "analysten", "intern", "praktikum", "werkstudent",
        "engineer", "manager", "consultant", "specialist", "coordinator",
        "data", "business", "ai", "machine learning", "stagiaire",
    ]
    location_keywords = [
        "zurich", "zuerich", "zug", "basel", "bern", "geneva",
        "winterthur", "wallisellen", "schweiz", "switzerland",
    ]
    
    for email in emails:
        html = email.get("html_body", "")
        text = email.get("text_body", "")
        body = html or text
        if not body:
            continue
        
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        
        job_blocks = []
        portal = email.get("from", "").split("@")[-1].split(">")[0].strip()
        
        # Pattern 1: Job title links
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            # separator=" ": without it, adjacent text nodes inside a
            # multi-element card (rating, title, location, CTA button all
            # in one <a>) get jammed together with no whitespace at all.
            raw_link_text = link.get_text(separator=" ", strip=True)

            if not raw_link_text or len(raw_link_text) < 5:
                continue

            # Skip mailto links and texts that are emails (alert footer,
            # e.g.: "Diese Nachricht wurde gesendet an <email>") -- avoids
            # leaking the candidate's email as if it were a job
            if href.lower().startswith("mailto:") or "@" in raw_link_text:
                continue

            title_lower = raw_link_text.lower()
            # \b avoids false positives like "ai" inside "gmail"
            if not any(re.search(r"\b" + re.escape(kw) + r"\b", title_lower) for kw in job_keywords):
                continue

            link_text = _strip_scraped_noise(raw_link_text)

            # Find nearby company and location
            parent = link.find_parent(["td", "div", "p", "li"])
            company = "Unknown"
            location = "Unknown"

            if parent:
                parent_text = parent.get_text(separator="\n", strip=True)
                lines = [_strip_scraped_noise(l) for l in parent_text.split("\n") if l.strip()]
                lines = [l for l in lines if l]

                for line in lines:
                    if line != link_text and len(line) > 2 and len(line) < 100:
                        if company == "Unknown":
                            company = line
                        elif location == "Unknown":
                            if any(loc in line.lower() for loc in location_keywords):
                                location = line

            job_blocks.append({
                "title": link_text,
                "company": company if company != link_text else "Unknown",
                "location": location,
                "url": href,
                "portal": portal,
                "source_email": email.get("subject", ""),
            })
        
        # Pattern 2: Plain text fallback
        if not job_blocks and text:
            patterns = [
                r'([A-Za-z\s/\-]+(?:Analyst|Engineer|Intern|Manager|Consultant)[A-Za-z\s/\-]*)\s+(?:at|@|bei)\s+([A-Za-z0-9\s\-&.]+)',
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    title = match.group(1).strip()
                    company = match.group(2).strip()
                    if len(title) > 5:
                        job_blocks.append({
                            "title": title,
                            "company": company,
                            "location": "Unknown",
                            "url": "",
                            "portal": portal,
                            "source_email": email.get("subject", ""),
                        })
        
        jobs.extend(job_blocks)
    
    # Deduplicate
    seen = set()
    unique = []
    for job in jobs:
        key = (job["title"].lower().strip(), job["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    
    print(f"  Extracted {len(unique)} jobs from {len(emails)} emails (local parser)")
    return unique


def main():
    os.makedirs("digests", exist_ok=True)
    
    emails_path = "digests/raw_emails_full.json"
    if not os.path.exists(emails_path):
        print(f"  No emails to parse: {emails_path} not found")
        with open("digests/parsed_jobs_latest.json", "w") as f:
            json.dump([], f)
        return
    
    with open(emails_path, "r", encoding="utf-8") as f:
        emails = json.load(f)
    
    if not emails:
        print("  No emails to parse")
        with open("digests/parsed_jobs_latest.json", "w") as f:
            json.dump([], f)
        return
    
    jobs = parse_html_emails(emails)
    
    with open("digests/parsed_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    
    print(f"  Saved {len(jobs)} parsed jobs to digests/parsed_jobs_latest.json")


if __name__ == "__main__":
    main()
