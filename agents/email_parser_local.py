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

    # Exact duplicates too, not just short/long pairs. Once the title is
    # extracted correctly from the card structure both variants produce the
    # SAME clean title, so the length difference this function relied on
    # disappears -- and the pair survived as two records, one of them with
    # company "Unknown". Keep one per title and take whatever real company,
    # location or url either copy happens to carry.
    merged: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        title = job["title"]
        if title in dropped:
            continue
        kept = merged.get(title)
        if kept is None:
            merged[title] = job
            continue
        for field in ("company", "location", "url", "description"):
            if kept.get(field, "Unknown") in ("Unknown", "", None):
                value = job.get(field)
                if value and value != "Unknown":
                    kept[field] = value
    return list(merged.values())


# Longest plausible employer name. Measured against every company the pipeline
# has ever stored correctly: the longest genuine one is "Zurich Insurance
# Company Ltd" territory, comfortably under this. Anything longer is not a
# company, it is a card that was never split.
MAX_COMPANY_CHARS = 45

# Words that mark a string as a ROLE rather than an employer. Used only to
# detect a card that put the two fields the wrong way round.
_ROLE_WORD = re.compile(
    r"\b(intern|internship|praktikum|praktikant|werkstudent|student|"
    r"engineer|developer|entwickler|analyst|scientist|manager|consultant|"
    r"specialist|associate|assistant|lead|architect|designer|"
    r"trainee|apprentice|graduate|junior|senior|architekt|ingenieur|berater)\b", re.I)


def _reject_implausible_company(company: str) -> str:
    """Returns the company, or "Unknown" when it is obviously not one.

    _split_card_remainder takes everything before the "." separator as the
    company, which is correct when it receives the tail of a card whose title
    has already been removed. When a card has no short/long twin there is no
    title to remove, so the WHOLE card became the company: 39 records across
    every day of the history carry a job title in the company field, including
    "Unknown (likely Palantir or similar ...)".

    Recovering the real name from an unstructured card is a heuristic that
    would misfire, and a wrong employer name is worse than none: it is written
    into a CV. So this only refuses the garbage. The cost is that the posting
    resolver cannot look the job up, which leaves it flagged
    insufficient_info -- visible, and honestly labelled as not understood.
    """
    name = str(company or "").strip()
    if not name or len(name) > MAX_COMPANY_CHARS:
        return "Unknown"
    # The model is asked to detect a company when the field is empty and
    # sometimes answers with a guess rather than a name.
    lowered = name.lower()
    if lowered.startswith("unknown") or "likely" in lowered:
        return "Unknown"
    return name


def _looks_like_a_role(text: str) -> bool:
    """Whether the text reads as a job title rather than an employer name."""
    return bool(_ROLE_WORD.search(str(text or "")))


def is_not_a_job_title(title: str) -> bool:
    """A card that is navigation or a promo rather than a posting.

    Deliberately narrow: only a SHORT title with no role word in it. The link
    reached this point because its text matched a job keyword, so "Data jobs"
    and "COURSE" (a LinkedIn course promo, which arrives with a duration such
    as "27m" where the employer should be) get through the keyword filter
    while being obviously not postings.

    A real title that happens to carry no role word -- "Data & AI Innovation
    & Portfolio" -- is long enough to be kept, which is the safe direction:
    scoring one piece of noise costs an API call, dropping one real posting
    costs a job.
    """
    text = str(title or "").strip()
    return len(text) < 25 and not _looks_like_a_role(text)


def _unswap(company: str, title: str):
    """Returns (company, title), swapped when the card put them the wrong way.

    Some boards emit the employer first, so the parser reads
    company="Founders Associate Intern", title="SaveSpace". The link was
    selected in the first place because its text contained a role keyword, so
    a title with no role word beside a company that has one is inverted --
    and the employer name is what ends up printed on a cover letter.

    Only swaps when the evidence points one way and not the other; when both
    or neither look like a role, it leaves them alone.
    """
    if _looks_like_a_role(company) and not _looks_like_a_role(title):
        return title, company
    return company, title


def tidy_job_fields(job: Dict[str, Any]) -> Dict[str, Any]:
    """Last-mile cleanup of one parsed card: company duplicated as a title
    prefix, locality glued to the title end. Mutates and returns the job."""
    job["company"], job["title"] = _unswap(job.get("company", ""), job.get("title", ""))
    job["company"] = _reject_implausible_company(job.get("company", ""))
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

                # The parent holds the card's real structure, one text node
                # per line:
                #
                #   [0] Internship in Data & AI Innovation & Portfolio (...)
                #   [1] Swiss International Air Lines . Kloten
                #
                # while link_text is the whole card flattened, because these
                # alerts wrap it in a single <a>. The old rule took the first
                # line that merely DIFFERED from link_text, so line 0 -- the
                # title -- became the company. 39 records across every day of
                # the history carried a job title as their employer name.
                #
                # A line the flattened link text STARTS WITH is the title. It
                # is never the company, and it is the clean title the card
                # actually meant.
                title_line = next(
                    (l for l in lines if len(l) > 5 and link_text.startswith(l)), "")
                if title_line and len(title_line) < len(link_text):
                    link_text = title_line

                for line in lines:
                    if len(line) <= 2 or len(line) >= 100:
                        continue
                    if line == link_text or (title_line and line == title_line):
                        continue
                    if company == "Unknown":
                        # "Company . City" is one node; split it rather than
                        # storing the whole thing as an employer name.
                        parsed_company, parsed_location = _split_card_remainder(line)
                        company = parsed_company or line
                        if parsed_location and location == "Unknown":
                            location = parsed_location
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
    collapsed = [j for j in _collapse_card_variants(jobs)
                 if not is_not_a_job_title(j.get("title", ""))]
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
