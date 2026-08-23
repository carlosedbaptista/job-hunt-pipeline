#!/usr/bin/env python3
"""
posting_resolver.py -- Finds the FULL text of a posting on the employer's own
applicant tracking system, because the job boards only ship a teaser.

Why this exists
---------------
Measured on 2026-08-23 across every Adzuna record ever stored: 917 of 917
descriptions were exactly 500 characters, all cut mid-sentence. What survives
the cut is the opening pitch; what is lost is the requirements list, which is
where the disqualifiers are. The Avaloq "AI Software Engineer" posting scored
82/APPLY on its teaser and 58/SKIP on the full text, which demands 5 years of
full-stack, 3 years of applied ML and a B.Sc.

Scraping the employer's careers page directly does not work: Adzuna's detail
page is JavaScript-rendered with no outbound link in the HTML, its /land/ and
/apply/ URLs answer 403, and employer sites (avaloq.com) answer 403 to a
runner. But most companies do not host their own postings -- they use an
applicant tracking system, and every major ATS exposes a public JSON board
with the complete text and no bot protection.

So: guess the company's ATS board from its name, fetch it, and match the
title. Nothing is scraped, nothing is rendered, and each provider is one
cheap request.

The two rules that keep this trustworthy
----------------------------------------
1. A provider only counts if its response VALIDATES as a real job board.
   Personio answers HTTP 200 with an identical 1.6 MB marketing page for any
   slug, invented ones included -- checking the status code alone would have
   "resolved" every company on earth.

2. A weak title match is REJECTED, never used. Feeding the evaluator the
   wrong posting's requirements is worse than feeding it nothing: it would be
   confidently, invisibly wrong. Verified case: "Machine Learning Intern,
   Autonomy" at Gravis Robotics is no longer on their Lever board, and the
   closest title there is "Senior Reinforcement Learning Engineer" at 0.48
   similarity. That must resolve to nothing.
"""
import argparse
import difflib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from utils import is_truncated_description  # noqa: E402

TIMEOUT = float(os.environ.get("RESOLVER_TIMEOUT", "12"))
# A match below this is discarded. 0.78 keeps "AI Engineer Intern" vs
# "AI Engineer Internship" (same job, 0.95) and rejects "Machine Learning
# Intern, Autonomy" vs "Senior Reinforcement Learning Engineer" (0.48).
MIN_TITLE_RATIO = float(os.environ.get("RESOLVER_MIN_TITLE_RATIO", "0.78"))
# Below this the "full" text is no better than the teaser it replaces.
MIN_USEFUL_CHARS = int(os.environ.get("RESOLVER_MIN_CHARS", "600"))

_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/xml, */*",
}

_LEGAL_SUFFIXES = (" ag", " gmbh", " sa", " sarl", " s.a.", " inc", " ltd", " llc",
                   " bv", " nv", " plc", " holding", " group", " schweiz", " switzerland")


def company_slugs(company: str):
    """Candidate board slugs for a company name, best guess first.

    ATS slugs are almost always the brand name with the legal suffix dropped:
    "BLP Digital AG" -> "blpdigital". Both the joined and hyphenated forms are
    tried because providers differ.
    """
    name = str(company or "").strip().lower()
    for suffix in _LEGAL_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    words = re.findall(r"[a-z0-9]+", name)
    if not words:
        return []
    out = ["".join(words)]
    if len(words) > 1:
        out.append("-".join(words))
        out.append(words[0])  # many boards use just the first word
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# One run sees the same employer many times -- BLP Digital alone accounted for
# 8 of 40 postings in the 2026-08-23 sample. Fetching its board once instead of
# eight times is the difference between this being affordable in CI and not.
_BOARD_CACHE = {}


def _cached(provider_name, slug, fetch):
    key = (provider_name, slug)
    if key not in _BOARD_CACHE:
        _BOARD_CACHE[key] = fetch(slug)
    return _BOARD_CACHE[key]


def _get(url):
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=_UA) as client:
            r = client.get(url)
        return r if r.status_code == 200 else None
    except Exception:
        return None


def _strip_html(raw):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", str(raw or ""), flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
                .replace("&quot;", '"'))
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


# ─── Providers ───────────────────────────────────────────────────────────────
# Each returns [(title, full_text)] or [] -- and returns [] rather than raising
# whenever the payload is not unmistakably a job board.

def _greenhouse(slug):
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not r:
        return []
    try:
        jobs = r.json().get("jobs", [])
    except ValueError:
        return []
    return [(j.get("title", ""), _strip_html(j.get("content", ""))) for j in jobs]


def _lever(slug):
    r = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not r:
        return []
    try:
        jobs = r.json()
    except ValueError:
        return []
    if not isinstance(jobs, list):
        return []
    out = []
    for j in jobs:
        text = j.get("descriptionPlain") or _strip_html(j.get("description", ""))
        extra = " ".join(_strip_html(s.get("text", "")) + " " + _strip_html(s.get("content", ""))
                         for s in (j.get("lists") or []))
        out.append((j.get("text", ""), (text + "\n" + extra).strip()))
    return out


def _smartrecruiters(slug):
    r = _get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    if not r:
        return []
    try:
        postings = r.json().get("content", [])
    except ValueError:
        return []
    out = []
    for p in postings:
        # The listing carries no body; the detail call does.
        detail = _get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{p.get('id')}")
        body = ""
        if detail:
            try:
                sections = detail.json().get("jobAd", {}).get("sections", {})
                body = " ".join(_strip_html((sections.get(k) or {}).get("text", ""))
                                for k in ("jobDescription", "qualifications", "additionalInformation"))
            except ValueError:
                body = ""
        out.append((p.get("name", ""), body.strip()))
    return out


def _recruitee(slug):
    r = _get(f"https://{slug}.recruitee.com/api/offers/")
    if not r:
        return []
    try:
        offers = r.json().get("offers", [])
    except ValueError:
        return []
    return [(o.get("title", ""),
             _strip_html(str(o.get("description", "")) + " " + str(o.get("requirements", ""))))
            for o in offers]


def _workable(slug):
    r = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    if not r:
        return []
    try:
        jobs = r.json().get("jobs", [])
    except ValueError:
        return []
    return [(j.get("title", ""),
             _strip_html(str(j.get("description", "")) + " " + str(j.get("requirements", ""))))
            for j in jobs]


def _ashby(slug):
    r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false")
    if not r:
        return []
    try:
        jobs = r.json().get("jobs", [])
    except ValueError:
        return []
    return [(j.get("title", ""), _strip_html(j.get("descriptionHtml", ""))) for j in jobs]


def _personio(slug):
    """Personio answers 200 with the SAME 1.6 MB marketing HTML for any slug,
    invented ones included. Only a parseable XML feed with <position> entries
    counts as a board."""
    r = _get(f"https://{slug}.jobs.personio.de/xml")
    if not r or "<position" not in r.text[:200000]:
        return []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []
    out = []
    for pos in root.iter("position"):
        title = (pos.findtext("name") or "").strip()
        body = " ".join(_strip_html(el.findtext("value") or "")
                        for el in pos.iter("jobDescription"))
        out.append((title, body.strip()))
    return out


PROVIDERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "smartrecruiters": _smartrecruiters,
    "recruitee": _recruitee,
    "workable": _workable,
    "personio": _personio,
}


def _norm_title(t):
    t = str(t or "").lower()
    t = re.sub(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\s*%|\b\d{1,3}\s*%", " ", t)   # "80-100%"
    t = re.sub(r"\(.*?\)|\b(m|w|d|f|all genders|all)\b[/\s]*", " ", t)     # "(m/w/d)"
    return re.sub(r"[^a-z0-9 ]", " ", t).strip()


def best_match(title, candidates):
    """The closest posting, or None when nothing is close enough."""
    want = _norm_title(title)
    best, best_ratio = None, 0.0
    for cand_title, text in candidates:
        ratio = difflib.SequenceMatcher(None, want, _norm_title(cand_title)).ratio()
        if ratio > best_ratio:
            best, best_ratio = (cand_title, text), ratio
    if not best or best_ratio < MIN_TITLE_RATIO:
        return None
    return {"matched_title": best[0], "text": best[1], "ratio": round(best_ratio, 2)}


def resolve(company, title, verbose=False):
    """Full posting text for company+title, or None.

    None is a perfectly good answer and by far the most common one. The caller
    keeps the teaser and the job stays flagged as low-confidence.
    """
    for slug in company_slugs(company):
        for provider_name, fetch in PROVIDERS.items():
            postings = _cached(provider_name, slug, fetch)
            if not postings:
                continue
            hit = best_match(title, postings)
            if verbose:
                print(f"    {provider_name}/{slug}: {len(postings)} postings, "
                      f"match={hit['ratio'] if hit else 'none'}")
            if not hit:
                continue
            text = hit["text"]
            if len(text) < MIN_USEFUL_CHARS or is_truncated_description(text):
                continue
            return {"provider": provider_name, "slug": slug, "url": None, **hit}
    return None


def main():
    ap = argparse.ArgumentParser(description="Find a posting's full text on the employer's ATS.")
    ap.add_argument("--company", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    hit = resolve(args.company, args.title, verbose=args.verbose)
    if not hit:
        print(f"Not found: {args.title} @ {args.company}")
        return 1
    print(f"Found on {hit['provider']} (slug '{hit['slug']}', title match {hit['ratio']})")
    print(f"Matched title: {hit['matched_title']}")
    print(f"{len(hit['text'])} chars\n")
    print(hit["text"][:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
