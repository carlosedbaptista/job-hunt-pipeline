# Job Hunt Pipeline

An unattended pipeline that finds engineering roles in Zurich, has tool-using
LLM agents investigate and score them against a candidate profile, and writes
a tailored CV and cover letter for the ones worth applying to. It has run
twice a day since June 2026 on GitHub Actions. No server, no manual step.

The interesting part is not that it works. It is what happened when I audited
it after three months.

---

## The audit

The pipeline had been running for months and looked healthy: jobs in, scores
out, a digest every morning. Then I measured what the model was actually
being shown.

**917 of 917 job descriptions were exactly 500 characters long, every one cut
mid-sentence.** The job board's API truncates them. What survives is the
opening pitch; what is lost is the requirements list, which is where the
disqualifiers live.

One posting made the cost concrete. An "AI Software Engineer" role scored
**82/100 — APPLY** on its 500-character teaser. On the full text it scored
**58 — SKIP**, because the posting demands five years of full-stack
development, three years of applied ML and a B.Sc.

The model was never wrong. It was handed 12% of the posting.

Across the whole history, **every score above the APPLY threshold had been
given on truncated or absent text**. Ten out of ten.

---

## What the fix required

The obvious repair — scrape the employer's careers page — does not work, and
proving that mattered more than guessing. The aggregator's detail page is
JavaScript-rendered with no outbound link in its HTML; its apply URLs answer
403; the employer's own site answers 403 to a CI runner; the Swiss public job
API returns its SPA shell for every path.

But employers mostly do not host their own postings. They use an applicant
tracking system, and every major ATS publishes a public JSON board carrying
the complete text with no bot protection.

[`agents/posting_resolver.py`](agents/posting_resolver.py) guesses a
company's board slug from its name and matches the title across Greenhouse,
Lever, Ashby, SmartRecruiters, Recruitee, Workable and Personio.

**Measured hit rate: 40%** over 40 real postings. Two rules keep the other
60% from becoming a subtler version of the same bug:

- a provider counts only if its payload **validates as a job board**. Personio
  answers HTTP 200 with an identical 1.6 MB marketing page for *any* slug,
  invented ones included, so trusting status codes would have "resolved"
  every company on earth;
- a title match below 0.78 is **rejected**. Handing the evaluator a different
  job's requirements would be confidently, invisibly wrong.

A miss is the ordinary case, and it is not a failure: the job keeps its
teaser, stays flagged as low-confidence, and can never reach APPLY or trigger
document generation. Half-knowledge that announces itself is trustworthy.
Confident half-knowledge is what produced the 82.

---

## Guardrails, because the model is not the authority

The LLM scores jobs, writes the CV summary and the cover letter, and drafts
follow-ups — and it now also deliberates, through the two agents below. Its
output is never trusted as-is.

The evaluator itself is now an agent, and the run around the jobs has one
too — both described in *The agent layer* below. What has not changed is
this section: the guardrails below remain enforced in code around whatever
the agents propose. One of them, the borderline re-sampling, is now the
rules-mode mechanism, since the agent investigates instead of re-sampling.

**The decision is derived in code, not read from the model.** A mandatory
German requirement is detected by a deterministic scan of the full posting
and locks the decision at SKIP regardless of the score. Before that scan
existed, a C1-German clause sitting past the excerpt window let a
disqualifying job score 96/100.

**Score noise is real and is bought off only where it matters.** Five
identical calls on one posting returned 55, 55, 55, 35 and 45 — twenty points
of drift on byte-identical input. It cannot be tuned away: the model rejects
every temperature setting but 1. It also mostly does not matter, since all
five still agreed on SKIP. It matters on a threshold, where the same job
becomes APPLY or REVIEW depending on which sample arrived. So a score landing
within one standard deviation of a boundary is scored three times and the
median kept — about 14% of jobs, at two extra calls each.

**A failed API call is an ERROR with a null score, never a number.** If every
evaluation in a run fails, the run exits non-zero rather than committing a
database that would mark three weeks of jobs as "already seen".

**Nothing in a generated document is invented.** When the cover letter
described "a guardrail firing too late in the sequence" — a plausible detail
that never happened — the fix was not a sterner prompt. It was noticing that
the generator passed the model a project *title* and no facts. Forbidding
invention cannot work while the facts are withheld.

---

## The agent layer

Two of the stages are not scripts but agents — an LLM in a loop with tools,
built on a 98-line runtime ([`src/agent_runtime.py`](src/agent_runtime.py))
with no framework.

The **decision agent** investigates every posting before scoring it: the full
text, a deterministic scan for mandatory languages over that full text, the
candidate profile, how past applications turned out, and how similar jobs
scored before. It commits through a mandatory decision tool, and the record
keeps its rationale and every tool call it made. What it cannot do is defined
in code: the guardrails above fence whatever it proposes.

The **orchestrator** makes the run-level calls a fixed YAML chain cannot:
whether to generate documents, fire alerts, draft follow-ups, or spend
leftover budget re-scoring last week's borderline jobs. Its floor is code —
any failure runs the legacy stage chain, so a bad orchestrator day is
indistinguishable from the pipeline before it existed. Every run writes a
committed log (`digests/orchestrator_log_*.json`): what it looked at, what it
did, why.

Both are switches, not bets: `EVALUATION_MODE=rules` and
`ORCHESTRATION_MODE=rules` restore the deterministic pipeline byte-for-byte.

The candidate's own signals stay his. Jobs he dismisses (with a reason) and
his reasons for applying live in a gitignored file, reach CI through a base64
secret, and enter the scorer's prompt only as aggregates. They are never
committed, never in the tracker database, never on the dashboard — the
repository is public, and job-hunt strategy is not public data.

---

## Measuring before fixing

Broad search queries multiplied intake by 7.7 and brought the noise with it:
consulting, marketing and M&A roles, each costing an LLM call before being
correctly rejected. The obvious fix was a keyword blacklist built from the
lowest-scoring titles.

Ranked by mean score, the two worst keywords in the entire history were
`praktikum` and `werkstudent` — German for *internship* and *working
student*, the exact roles being searched for. They scored low because those
particular postings did not fit, not because the words signal noise. The
blacklist would have deleted the entire German-language funnel, silently.

The gate that shipped is a conjunction instead: a non-technical *function*
with no technical term anywhere in the title. Validated against all 278
scored titles, it drops 13%, and the highest score among everything it drops
is 35 — half the REVIEW threshold. The test re-derives that guarantee from
the committed history on every run rather than trusting the claim.

---

## Architecture

```
GitHub Actions (cron, 05:00 and 12:00 UTC)
  |
  |-- Adzuna ingestor        18 queries, one location, 30 km radius
  |-- Gmail IMAP             job alert e-mails
  |-- Local parser           regex + BeautifulSoup, no API
  |
  |-- Unified ingestor       dedup (SQLite, 21-day window), relevance gate,
  |                          cost cap applied BEFORE marking jobs as seen
  |-- Posting resolver       full text from the employer's ATS
  |-- Decision agent (Kimi)  tool-using; APPLY/REVIEW/SKIP with rationale,
  |                          safety rails enforced in code
  |-- Orchestrator (Kimi)    run-level judgement: docs, alerts, follow-ups, re-scores
  |
  |-- Digest + dashboard
  |-- Document generator     tailored CV and cover letter, PDF and .docx
  |-- Google Drive (OAuth2, drive.file scope)
  '-- Gmail SMTP
```

| | |
|---|---|
| Language | Python 3.11 |
| LLM | Kimi (Moonshot), `kimi-k2.6` |
| Storage | SQLite, JSON artefacts |
| Documents | fpdf2, python-docx |
| CI | GitHub Actions; pytest on every push |
| Tests | 436, LLM mocked, no network |

---

## Cost control

The job API's free tier is 100 calls a day. The pipeline spends 36 and the
arithmetic is asserted by a test, not left in a comment, because it is
exactly the kind of thing one innocent extra query breaks.

The LLM cap is applied *before* jobs are marked as seen. An earlier version
marked everything seen and then evaluated the first 30, so jobs 31 and beyond
were silently swallowed forever.

Agent mode spends more model calls by design: an investigated job costs two
to five calls instead of one, and the orchestrator adds a bounded slice on
top. The brakes are in code, not in prompts: a 30-job evaluation cap, a hard
iteration limit per conversation, and a re-score budget the orchestrator
cannot exceed no matter what it asks for.

---

## Setup

Full instructions: [`GITHUB_ACTIONS_SETUP.md`](GITHUB_ACTIONS_SETUP.md) ·
Drive: [`config/GDRIVE_SETUP.md`](config/GDRIVE_SETUP.md)

```bash
git clone https://github.com/carlosedbaptista/job-hunt-pipeline.git
cd job-hunt-pipeline
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The candidate profile, photo and document voice references are kept out of
this repository and restored in CI from base64 secrets. This repo is public;
nothing carrying personal data belongs in it.

---

## Running it by hand

The manual workflow takes three inputs, all off by default and never set by
the scheduled runs: `skip_ingestion` reuses the batch already fetched,
`reevaluate` re-scores jobs already seen, and `max_evaluations` caps the LLM
calls. Together they make the whole pipeline runnable any number of times
without spending job-board quota — which is the difference between a system
you can test and one you can only hope about.

Two switches and two probes round it out: `EVALUATION_MODE` and
`ORCHESTRATION_MODE` (`agent` or `rules`) decide who evaluates and who
orchestrates, and `scripts/smoke_decision_agent.py` and
`scripts/smoke_orchestrator.py` run the real agents against synthetic
postings, so their reasoning can be watched without touching a real run.

---

*Built by [Carlos Baptista](https://linkedin.com/in/carlosedbaptista).*
