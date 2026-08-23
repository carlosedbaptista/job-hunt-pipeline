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


# Alert-navigation links that contain a job keyword and therefore survive the
# keyword filter, but are not jobs: the alert header ("Your job alert for
# intern in the past 24 hours"), footer and unsubscribe rows. Two of them
# reached the evaluator in data/history and burned an LLM call each to be
# scored 0/SKIP.
_ALERT_LINK_RE = re.compile(
    r"your job alert|job alert for|see (?:all|more) jobs|view (?:all|more)"
    r"|all jobs? (?:in|for)|unsubscribe|abmelden|manage (?:your )?alerts"
    r"|jobbenachrichtigung|see jobs? like|\d+\s+new jobs?",
    re.IGNORECASE,
)


def _is_alert_navigation(text: str) -> bool:
    return bool(_ALERT_LINK_RE.search(text or ""))


# CTA/status suffixes that trail the company/location block on a job card.
_CARD_TAIL_RE = re.compile(
    r"\b(?:easy apply|einfache bewerbung|be an early applicant|promoted|gesponsert"
    r"|actively recruiting|verified)\b.*$",
    re.IGNORECASE,
)

# Swiss localities that job cards glue onto the end of the title.
_TRAILING_CITY_RE = re.compile(
    r"[\s,;-]+((?:Z[uü]rich|Zuerich|Zug|Basel|Bern|Genf|Gen[eè]ve|Geneva|Lausanne"
    r"|Winterthur|Wallisellen|Luzern|St\.?\s?Gallen|Baar|Cham|Schlieren|Opfikon"
    r"|Glattbrugg|D[uü]bendorf|Zollikon|Frick)(?:\s*,?\s*(?:CH|Schweiz|Switzerland))?)\s*$",
    re.IGNORECASE,
)


def _split_card_remainder(remainder: str):
    """Parses the '<company> · <location> (Hybrid) Easy Apply' tail a job card
    appends after its title. Returns (company, location); either may be ''
    when the tail does not carry it."""
    tail = _CARD_TAIL_RE.sub("", remainder or "").strip(" ·•|-–—,")
    if not tail:
        return "", ""
    parts = [p.strip() for p in re.split(r"[·•|]", tail) if p.strip()]
    if len(parts) >= 2:
        company = parts[0]
        # "Zurich, Switzerland (Hybrid)" -> "Zurich, Switzerland"
        location = re.sub(r"\s*\([^)]*\)\s*$", "", parts[1]).strip()
        return company, location
    single = re.sub(r"\s*\([^)]*\)\s*$", "", parts[0]).strip()
    # A lone tail is a company name unless it reads like a locality.
    return ("", single) if _TRAILING_CITY_RE.search(" " + single) else (single, "")


def _strip_company_prefix(title: str, company: str) -> str:
    """Glassdoor renders '<Company> <Job title> <City>' as one blob while the
    company is also extracted into its own field. Drop the duplicated prefix
    so the title is just the title."""
    if not company or company == "Unknown":
        return title
    if title.lower().startswith(company.lower() + " "):
        return title[len(company):].strip(" -–—,") or title
    return title


def _split_trailing_city(title: str):
    """Moves a locality glued to the end of a card title into its own field.
    Returns (title_without_city, city); city is '' when there is none."""
    m = _TRAILING_CITY_RE.search(title or "")
    if not m:
        return title, ""
    return title[: m.start()].rstrip(" ,;-"), m.group(1).strip()


def _collapse_card_variants(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One job card is emitted twice by these alerts: once as the bare title
    (an inner <a>) and once as the whole card blob (the wrapping <a>:
    '<title> <company> · <location> (Hybrid) Easy Apply'). Both survived the
    (title, company) dedup below, so the same posting was evaluated twice --
    36 of the 187 distinct titles in data/history are one of these pairs --
    and the clean variant carried neither company nor location.

    Collapse them: keep the short, clean title and harvest company/location
    out of the long variant's remainder."""
    by_title: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        by_title.setdefault(job["title"], job)

    titles = sorted(by_title, key=len)
    dropped = set()
    for short in titles:
        if not short or short in dropped:
            continue
        for long in titles:
            if long in dropped or long == short or not long.startswith(short + " "):
                continue
            base, variant = by_title[short], by_title[long]
            company, location = _split_card_remainder(long[len(short):])
            if company and base.get("company", "Unknown") in ("Unknown", "", None):
                base["company"] = company
            if location and base.get("location", "Unknown") in ("Unknown", "", None):
                base["location"] = location
            if not base.get("url"):
                base["url"] = variant.get("url", "")
            dropped.add(long)

    return [j for j in jobs if j["title"] not in dropped]


def tidy_job_fields(job: Dict[str, Any]) -> Dict[str, Any]:
    """Last-mile cleanup of one parsed card: company duplicated as a title
    prefix, locality glued to the title end. Mutates and returns the job."""
    job["title"] = _strip_company_prefix(job["title"], job.get("company", ""))
    title, city = _split_trailing_city(job["title"])
    if city:
        job["title"] = title
        if job.get("location", "Unknown") in ("Unknown", "", None):
            job["location"] = city
    return job


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

            # Alert header/footer navigation ("Your job alert for intern...")
            # matches the job keywords but is not a posting.
            if _is_alert_navigation(raw_link_text):
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
    
    # Collapse the bare-title / whole-card pair BEFORE the (title, company)
    # dedup: the two variants have different titles, so that dedup never saw
    # them as the same posting.
    collapsed = _collapse_card_variants(jobs)
    variants_merged = len(jobs) - len(collapsed)

    # Deduplicate
    seen = set()
    unique = []
    for job in collapsed:
        tidy_job_fields(job)
        key = (job["title"].lower().strip(), job["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)

    print(f"  Extracted {len(unique)} jobs from {len(emails)} emails (local parser)"
          f"{f'; {variants_merged} duplicate card variants merged' if variants_merged else ''}")
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
