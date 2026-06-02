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
            link_text = link.get_text(strip=True)
            
            if not link_text or len(link_text) < 5:
                continue
            
            title_lower = link_text.lower()
            if not any(kw in title_lower for kw in job_keywords):
                continue
            
            # Find nearby company and location
            parent = link.find_parent(["td", "div", "p", "li"])
            company = "Unknown"
            location = "Unknown"
            
            if parent:
                parent_text = parent.get_text(separator="\n", strip=True)
                lines = [l.strip() for l in parent_text.split("\n") if l.strip()]
                
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
