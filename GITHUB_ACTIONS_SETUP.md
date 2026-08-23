# GitHub Actions setup

Everything runs in GitHub Actions. There is no server, and nothing needs to
run on your machine.

The LLM is **Kimi (Moonshot)**. Nothing in this pipeline calls the Anthropic
API, and there is no `ANTHROPIC_API_KEY`; an earlier version of this document
told you to create one, which was wrong and has been removed.

## Secrets

*Settings → Secrets and variables → Actions*

| Secret | Required | What it is |
|---|---|---|
| `KIMI_API_KEY` | yes | platform.moonshot.ai. Must have balance: with none, every evaluation returns ERROR and the run fails loudly on purpose |
| `KIMI_BASE_URL` | optional | Only to force `.ai` vs `.cn` |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | yes | Job search. Free tier is 100 calls/day |
| `GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, `GMAIL_RECIPIENT` | yes | Digest, alerts and document delivery. The password is a 16-character App Password, not your Gmail password |
| `CANDIDATE_PROFILE_B64` | yes | `config/candidate_profile.json` in base64. Without it the evaluator exits 1 rather than scoring against a generic profile |
| `CANDIDATE_PHOTO_B64` | optional | CV photo |
| `CV_MODEL_B64`, `CL_MODEL_B64` | optional | Voice references for the generated documents |
| `GDRIVE_REFRESH_TOKEN_B64` | optional | Drive upload. See `config/GDRIVE_SETUP.md` |
| `GDRIVE_PARENT_FOLDER_ID` | optional | Drive root folder id |

Generate the base64 values (Git Bash), and note `-w0`: a wrapped value breaks
the restore step.

```bash
base64 -w0 config/candidate_profile.json   # CANDIDATE_PROFILE_B64
base64 -w0 config/photo.jpg                # CANDIDATE_PHOTO_B64
base64 -w0 config/cv_model.txt             # CV_MODEL_B64
base64 -w0 config/cover_letter_model.txt   # CL_MODEL_B64
```

These files are gitignored. The repository is **public**: nothing carrying
personal data belongs in it.

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `job-hunt-scheduler.yml` | 05:00 and 12:00 UTC, or manual | The daily pipeline |
| `tests.yml` | every push and PR | pytest and compileall. No secrets |
| `add-job.yml` | manual | Evaluate one posting you paste in, and generate CV/CL if it scores APPLY |
| `track-application.yml` | manual | Record that you applied, or a recruiter reply |

All three that write to the repository share the `job-hunt-repo-write`
concurrency group: `tracker/jobs.db` is a binary SQLite file and two
concurrent writers cannot be merged.

## Running it by hand

*Actions → Job Hunt Daily Pipeline → Run workflow*, with three inputs, all
off by default and never set by the scheduled runs:

| Input | Use |
|---|---|
| `skip_ingestion` | Reuse the batch already fetched. Calls no external API |
| `reevaluate` | Re-score jobs already marked as seen |
| `max_evaluations` | Cap LLM calls for this run. Use 3-5 when testing |

The first two exist because Adzuna's free tier is 100 calls a day and one run
spends 18, so on a day of testing there is no budget for a second fetch; and
because cross-run deduplication otherwise leaves a second run with nothing to
score. Together they make the whole pipeline runnable any number of times for
the cost of the LLM calls alone.

## Checking a run

Four lines in the log tell you whether it worked:

```
Relevance gate: N clearly off-target ... dropped before scoring
Description enricher: N/M descriptions are TRUNCATED
  Recovered the full posting for N/M from the employers' own job boards
DONE: N jobs | APPLY: n | REVIEW: n | SKIP: n | ERROR: n
```

`ERROR` above zero usually means the Kimi key has no balance. If every
evaluation fails the run exits 1 deliberately, so a silent billing lapse
cannot quietly destroy three weeks of job discovery.

## Cost

GitHub Actions is free for public repositories. The pipeline spends about
four minutes per run.

Adzuna: 18 search calls per run, 36 a day, against a free tier of 100. The
posting resolver costs no Adzuna quota at all -- it reads the employers' own
ATS boards, which are different hosts.

Kimi: at most `MAX_EVALUATIONS_PER_RUN` (30) calls per run, plus two extra
for each job whose score lands within 8 points of a decision threshold and is
therefore re-scored to break the tie. Measured on a real run: 4 of 29 jobs,
so 8 extra calls.
