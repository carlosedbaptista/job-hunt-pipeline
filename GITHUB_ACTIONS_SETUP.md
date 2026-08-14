# Week 7: GitHub Actions Scheduler — Complete Setup

> **UPDATE (2026-08):** the pipeline uses the **Kimi/Moonshot** API (no longer Anthropic).
> Required secrets in *Settings → Secrets and variables → Actions*:
>
> | Secret | Required | Description |
> |---|---|---|
> | `KIMI_API_KEY` | yes | Key from platform.moonshot.ai (must have balance!) |
> | `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | yes | Adzuna jobs API |
> | `GMAIL_SENDER` / `GMAIL_APP_PASSWORD` / `GMAIL_RECIPIENT` | yes | Email sending (16-char App Password) |
> | `CANDIDATE_PROFILE_B64` | recommended | `candidate_profile.json` in base64 (keeps PII out of git) |
> | `CANDIDATE_PHOTO_B64` | optional | `photo.png` in base64 (CV photo) |
> | `CV_MODEL_B64` | optional | `cv_model.txt` in base64 (real CV template used for tailoring) |
> | `CL_MODEL_B64` | optional | `cover_letter_model.txt` in base64 (real CL template) |
> | `GDRIVE_PARENT_FOLDER_ID` / `GDRIVE_REFRESH_TOKEN_B64` / `GDRIVE_CREDENTIALS_JSON_B64` | optional | Upload of CVs/CLs to Drive |
>
> Generate the base64 values (Git Bash):
> ```bash
> base64 -w0 config/candidate_profile.json   # paste as CANDIDATE_PROFILE_B64
> base64 -w0 config/photo.png                # paste as CANDIDATE_PHOTO_B64
> base64 -w0 config/cv_model.txt             # paste as CV_MODEL_B64
> base64 -w0 config/cover_letter_model.txt   # paste as CL_MODEL_B64
> ```
>
> Without `CANDIDATE_PROFILE_B64` the pipeline runs with a generic fallback profile
> (worse matching and no personalized CV/CL generation).

## What you did

You created a **GitHub Actions workflow** that:
- ✅ Runs automatically every day at **7:00 AM** (Switzerland time)
- ✅ Executes the full pipeline (ingest → parse → eval → digest)
- ✅ Generates the dashboard automatically
- ✅ Commits the updated files to the repo

---

## Required Configuration

### STEP 1: Add Secret on GitHub

Your workflow is already configured to read the Anthropic API key from a GitHub **Secret**.

1. Go to: https://github.com/your-username/job-hunt-pipeline/settings/secrets/actions

2. Click **"New repository secret"**

3. Name: `ANTHROPIC_API_KEY`
   Value: `sk-ant-your-key-here`

4. Click **"Add secret"**

✅ Done! GitHub Actions can now run Claude.

---

### STEP 2: The Gmail API Problem (Important!)

⚠️ **WARNING:** GitHub Actions runs on a Linux server with no access to your computer.

**Problem:**
- Gmail API needs `token.pickle` (generated on your computer)
- GitHub cannot access your local file

**Solutions:**

#### Option A: Run locally via Cron/Task Scheduler (Recommended)
If you want to make sure it works:

**On Windows:**
1. Open "Task Scheduler"
2. Create a task that runs: `python src/week4_pipeline.py`
3. Schedule it for 7:00 AM every day

**On Mac/Linux:**
```bash
# Create a cron job
crontab -e

# Add (7 AM every day):
0 7 * * * cd ~/job-hunt-pipeline && python src/week4_pipeline.py
```

#### Option B: GitHub Actions + Manual Fallback
Keep GitHub Actions enabled, but:
- If it fails (because of Gmail), you run it manually on the weekend
- At least it generates a digest with older jobs (useful even without new emails)

#### Option C: Use Google Cloud for Gmail (Advanced)
- Set up Google Cloud Scheduler
- Trigger a function that runs the pipeline
- Expensive, but 100% automatic

---

## Test the Workflow

### Test 1: Run Manually on GitHub

1. Go to: https://github.com/your-username/job-hunt-pipeline/actions

2. Click **"Job Hunt Daily Pipeline"**

3. Click **"Run workflow"** → **"Run workflow"**

4. Wait 2-5 minutes

5. If it shows ✅ green = success, if ❌ red = failed

### Test 2: Check the updated files

If it ran successfully, it should have committed:
- `digests/digest_latest.json` updated
- `digests/dashboard.html` updated

---

## Schedule (Cron)

Your workflow is configured for:

```
0 5 * * *
│ │ │ │ └─ Day of week (0-6, 0 is Sunday)
│ │ │ └─── Month (1-12)
│ │ └───── Day of month (1-31)
│ └─────── Hour (UTC, 0-23)
└───────── Minute (0-59)
```

**0 5 * * * = 5:00 AM UTC = 7:00 AM CEST (summer in Switzerland)**

If you want to change the time, edit `.github/workflows/job-hunt-scheduler.yml`

Examples:
- `0 6 * * *` = 8:00 AM CEST
- `0 8 * * *` = 10:00 AM CEST
- `0 20 * * *` = 22:00 (10 PM) CEST

---

## What happens when it runs

1. ✅ GitHub pulls your repo
2. ✅ Installs dependencies (pip install -r requirements.txt)
3. ✅ Runs `python src/week4_pipeline.py`
   - Fetches emails from Gmail
   - Parses jobs with Claude
   - Evaluates fit
   - Generates digest
4. ✅ Commits and pushes the updated files
5. ✅ You receive a notification (optional, via GitHub)

---

## Logs and Debugging

If something goes wrong:

1. Go to: GitHub → Actions → Job Hunt Daily Pipeline

2. Click the failed run

3. Click **"job-hunt-pipeline"**

4. View the output (where the error is)

Common errors:
- `ModuleNotFoundError` = requirements.txt is missing a package
- `authentication_error` = Secret was not added
- `Gmail error` = token.pickle is not accessible (expected)

---

## Final Recommendation

**Use GitHub Actions ONLY as a backup.**

To guarantee it works 100%, set up a **local Cron Job** (Option A above) on your computer.

That way:
- ✅ GitHub Actions runs (generates digest even without new emails)
- ✅ Local cron runs (fetches new emails every morning)
- ✅ Robust system with redundancy

---

## Next Optimizations (Week 8+)

- [ ] Set up notifications (email when there are new jobs)
- [ ] Add Google Cloud Function for Gmail (remove the need for token.pickle)
- [ ] Create webhook to send digest by email
- [ ] Analytics: which type of job gets the best response?
