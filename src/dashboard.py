"""
dashboard.py  —  Generates the interactive HTML dashboard (improved version)
Features: Chart.js, dark mode, filters, CSV export, 30-day history
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import THRESHOLD_APPLY, THRESHOLD_REVIEW, has_hard_blocker
from src.deduplicator import normalize, normalize_company

# Paths
DIGESTS_DIR = "digests"
DATA_DIR = "data"
HISTORY_DIR = "data/history"


def load_json(path):
    """Tolerant read. The commit step runs with `if: always()`, so a run
    killed mid-write persists a truncated JSON file; a bare json.load then
    aborts the dashboard step, which is NOT continue-on-error, taking the
    doc-generation, alert and follow-up steps down with it."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        print(f"  WARNING: skipping unreadable {path} ({type(e).__name__}: {e})")
        return None


def _js_safe(payload: str) -> str:
    """Makes a JSON payload safe to inline inside a <script> block.

    json.dumps escapes quotes and backslashes but NOT `<`, so a posting
    containing `</script>` closes the tag early: JOBS is never defined, the
    public GitHub Pages dashboard renders empty, and whatever followed the
    tag is parsed as markup. The payload carries titles, companies and
    descriptions scraped from third-party job alerts, i.e. text this repo
    does not control. The JS-side esc() cannot help -- the break-out happens
    before any JS runs. Escaping to \u003c keeps the JSON byte-identical
    once parsed."""
    return (payload.replace("<", "\\u003c")
                   .replace(">", "\\u003e")
                   .replace("&", "\\u0026")
                   .replace("\u2028", "\\u2028")
                   .replace("\u2029", "\\u2029"))


def parse_digest_date(filename):
    """Extracts the date from the digest_YYYYMMDD_HHMM.json filename."""
    basename = os.path.basename(filename)
    if basename == "digest_latest.json":
        return datetime.now().strftime("%Y-%m-%d")
    # digest_20260602_1636.json -> 2026-06-02
    try:
        parts = basename.replace("digest_", "").replace(".json", "").split("_")
        return f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}"
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def collect_jobs(days=30):
    """Collects evaluations from the last N days from the historical digests."""
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    all_jobs = []
    seen_keys = set()

    def add_eval(ev, digest_date, manual=False):
        """Adds one evaluation to the list, skipping duplicates and API errors."""
        # ERROR is a failure and is excluded. NOT_EVALUATED is not a failure:
        # the posting was found, its text was never readable, and hiding it
        # would leave the owner wondering where a job he saw in an alert
        # went. It is shown, labelled, and carries no score.
        if ev.get("decision") == "ERROR":
            return
        no_text = bool(ev.get("no_posting_text")) or ev.get("decision") == "NOT_EVALUATED"
        if ev.get("score") is None and not no_text:
            return
        job = ev.get("job", ev)
        # Identity is normalized company+title -- NOT the URL: the same
        # posting arrives with a different tracking URL per source/visit,
        # and a manual re-evaluation (which REPLACES the old record by
        # design) used to be shadowed by the older history entry that
        # happened to share the URL. Manual entries are added first below
        # precisely so the newest evaluation wins the dedup race.
        key = f"{normalize_company(job.get('company', ''))}|{normalize(job.get('title', ''))}"
        if key in seen_keys:
            return
        seen_keys.add(key)
        ev_copy = dict(ev)
        ev_copy["_digest_date"] = digest_date
        # Precomputed for the JS: hard-blocker lock and low-confidence cap
        # (mirrors utils.effective_decision, incl. legacy records without
        # the structured hard_blockers field).
        ev_copy["_has_blocker"] = has_hard_blocker(ev)
        ev_copy["_insufficient"] = bool(ev.get("insufficient_info"))
        ev_copy["_lang_gap"] = bool(ev.get("language_gap_intermediate"))
        ev_copy["_no_text"] = no_text
        if manual:
            ev_copy["_manual"] = True
        all_jobs.append(ev_copy)

    # 0. Manually added jobs FIRST (via the "Add Job" workflow or
    # agents/add_job.py): re-evaluating a posting deliberately replaces the
    # old record, so the newest score must win against history/digests.
    manual = load_json(os.path.join(DIGESTS_DIR, "manual_evaluations.json"))
    if manual and isinstance(manual, list):
        for ev in manual:
            manual_date = str(ev.get("evaluated_at", ""))[:10] or datetime.now().strftime("%Y-%m-%d")
            add_eval(ev, manual_date, manual=True)

    # 1. Full evaluation history (data/history/evaluations_YYYYMMDD.json),
    # written by job_evaluator -- richer than the top-5 kept in digests.
    # NEWEST FIRST. add_eval keeps the first record it sees per key, and
    # ascending order therefore let an OLD blind evaluation beat the newer
    # re-evaluation of the same posting -- e.g. scored 72/insufficient_info
    # on day 1, re-ingested on day 23 after the 21-day retention expires,
    # enriched with the real description and scored 88/APPLY, and the
    # dashboard still showed the day-1 record (and computed the 10-day "No
    # action" inference from the stale date). Manual entries are merged
    # before this loop and still win over everything.
    for hfile in sorted(glob.glob(os.path.join(HISTORY_DIR, "evaluations_*.json")), reverse=True):
        basename = os.path.basename(hfile)
        try:
            d = basename.replace("evaluations_", "").replace(".json", "")
            hist_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        except Exception:
            hist_date = datetime.now().strftime("%Y-%m-%d")
        if hist_date < cutoff_str:
            continue
        data = load_json(hfile)
        if data and isinstance(data, list):
            for ev in data:
                add_eval(ev, hist_date)

    # 2. Historical digests
    # Newest first, same reasoning as the history loop above.
    digest_files = sorted(glob.glob(os.path.join(DIGESTS_DIR, "digest_*.json")), reverse=True)
    for dfile in digest_files:
        digest_date = parse_digest_date(dfile)
        if digest_date < cutoff_str and dfile != os.path.join(DIGESTS_DIR, "digest_latest.json"):
            continue

        data = load_json(dfile)
        if not data or not isinstance(data, dict):
            continue

        jobs = data.get("top_jobs", [])
        for ev in jobs:
            add_eval(ev, digest_date)

    # 3. Current evaluations (job_evaluations_latest.json)
    evals = load_json(os.path.join(DIGESTS_DIR, "job_evaluations_latest.json"))
    if evals and isinstance(evals, list):
        today = datetime.now().strftime("%Y-%m-%d")
        for ev in evals:
            add_eval(ev, today)

    return all_jobs


def load_application_status() -> dict:
    """Loads applications from tracker/jobs.db, keyed by normalized
    company+title (same normalisation as the dedup hash), so dashboard
    rows can show whether -- and how -- the user acted on each job.
    Only structured fields are surfaced (status, response_type,
    date_applied): free-text `notes` are excluded on purpose, since this
    dashboard is published to a public GitHub Pages site."""
    try:
        from agents.tracker_updater import get_all_applications
        lookup = {}
        for app in get_all_applications():
            key = f"{normalize_company(app.get('company', ''))}|{normalize(app.get('title', ''))}"
            lookup[key] = {
                "status": app.get("status"),
                "response_type": app.get("response_type"),
                "date_applied": app.get("date_applied"),
            }
        return lookup
    except Exception as e:
        print(f"WARNING: could not load application status: {e}")
        return {}


def attach_application_status(jobs: list, app_lookup: dict) -> list:
    """Annotates each job with `_application_status` when a tracked
    application matches it by normalized company+title."""
    for job in jobs:
        j = job.get("job", job)
        company = j.get("company", "")
        title = j.get("title", "")
        key = f"{normalize_company(company)}|{normalize(title)}"
        match = app_lookup.get(key)
        if match:
            job["_application_status"] = match
    return jobs


def get_template_head():
    """Returns the first part of the HTML template (up to const JOBS)."""
    return r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunt Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg: #f5f5f5; --card: #fff; --text: #333; --muted: #666;
            --accent: #667eea; --accent2: #764ba2; --success: #32CD32;
            --warning: #FFA500; --danger: #ff4444; --border: #e0e0e0;
        }
        body.dark {
            --bg: #1a1a2e; --card: #16213e; --text: #eee; --muted: #aaa;
            --border: #2a2a4a;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg); color: var(--text); transition: background 0.3s, color 0.3s;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
            color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px;
        }
        header h1 { font-size: 28px; margin-bottom: 5px; }
        header p { opacity: 0.9; font-size: 14px; }
        .toggle-btn {
            float: right; background: rgba(255,255,255,0.2); border: none;
            color: white; padding: 8px 16px; border-radius: 6px; cursor: pointer;
        }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .card {
            background: var(--card); border-radius: 10px; padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08); border: 1px solid var(--border);
        }
        .card h3 { font-size: 14px; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .metric { font-size: 36px; font-weight: 700; color: var(--accent); }
        .metric.green { color: var(--success); }
        .metric.orange { color: var(--warning); }
        .metric.red { color: var(--danger); }
        .filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
        .filters input, .filters select {
            padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px;
            background: var(--card); color: var(--text); font-size: 14px;
        }
        .filters input { flex: 1; min-width: 200px; }
        .btn {
            padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer;
            font-size: 14px; font-weight: 600; transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.85; }
        .btn-primary { background: var(--accent); color: white; }
        .btn-success { background: var(--success); color: white; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 12px; font-size: 12px; text-transform: uppercase; color: var(--muted); border-bottom: 2px solid var(--border); }
        td { padding: 12px; border-bottom: 1px solid var(--border); }
        tr:hover { background: rgba(102,126,234,0.05); }
        .badge { padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; }
        .badge-apply { background: #e8f5e9; color: #2e7d32; }
        .dark .badge-apply { background: #1b5e20; color: #a5d6a7; }
        .badge-review { background: #fff3e0; color: #ef6c00; }
        .dark .badge-review { background: #e65100; color: #ffcc80; }
        .badge-skip { background: #ffebee; color: #c62828; }
        .badge-unknown { background: #eceff1; color: #546e7a; }
        .dark .badge-unknown { background: #37474f; color: #cfd8dc; }
        .dark .badge-skip { background: #b71c1c; color: #ef9a9a; }
        .badge-applied { background: #e3f2fd; color: #1565c0; }
        .dark .badge-applied { background: #0d47a1; color: #90caf9; }
        .badge-interview { background: #e8f5e9; color: #1b5e20; }
        .dark .badge-interview { background: #1b5e20; color: #a5d6a7; }
        .badge-rejected { background: #ffebee; color: #b71c1c; }
        .dark .badge-rejected { background: #4a0e0e; color: #ef9a9a; }
        .badge-noaction { background: transparent; color: var(--muted); border: 1px dashed var(--border); }
        .score { font-weight: 700; }
        .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .charts .card { padding: 15px; }
        canvas { max-height: 250px; }
        .profile { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
        .profile-item { font-size: 13px; color: var(--muted); }
        .profile-item strong { color: var(--text); display: block; margin-bottom: 2px; }
        .empty { text-align: center; padding: 60px 20px; color: var(--muted); }
        .hidden { display: none; }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .charts { grid-template-columns: 1fr; }
            .filters { flex-direction: column; }
            th, td { font-size: 13px; padding: 8px; }
        }
    </style>
</head>
<body>
<div class="container">
    <header>
        <button class="toggle-btn" onclick="toggleDark()">Dark Mode</button>
        <h1>Job Hunt Dashboard</h1>
        <p>Automated job search &amp; evaluation pipeline &middot; <a href="https://github.com/carlosedbaptista/job-hunt-pipeline/actions/workflows/add-job.yml" target="_blank">+ Add a job manually</a> &middot; <a href="https://github.com/carlosedbaptista/job-hunt-pipeline/actions/workflows/track-application.yml" target="_blank">+ Track an application</a> (Actions &rarr; Run workflow)</p>
    </header>

    <!-- Attribution only. The full profile card that used to sit here also
         printed permit status, notice period and languages onto a page served
         publicly with no authentication; none of that is needed to read a job
         list, and it made a working tool read as a personal page. The owner
         asked to keep the LinkedIn link, which is deliberate: this dashboard
         doubles as portfolio, and someone who finds it should be able to find
         him. That link is already public on his profile. -->
    <div class="card" style="margin-bottom: 20px; display:flex; align-items:center;
         justify-content:space-between; flex-wrap:wrap; gap:10px;">
        <div style="color:#666; font-size:14px;">
            Built and maintained by
            <a href="https://www.linkedin.com/in/carlosedbaptista/" target="_blank"
               rel="noopener">Carlos Baptista</a>
        </div>
        <div style="color:#999; font-size:13px;">
            <a href="https://github.com/carlosedbaptista/job-hunt-pipeline"
               target="_blank" rel="noopener">Source on GitHub</a>
        </div>
    </div>

    <!-- Metrics -->
    <div class="grid">
        <div class="card">
            <h3>Total Evaluated</h3>
            <div class="metric" id="metric-total">0</div>
        </div>
        <div class="card">
            <h3>APPLY</h3>
            <div class="metric green" id="metric-apply">0</div>
        </div>
        <div class="card">
            <h3>REVIEW</h3>
            <div class="metric orange" id="metric-review">0</div>
        </div>
        <div class="card">
            <h3>SKIP</h3>
            <div class="metric red" id="metric-skip">0</div>
        </div>
        <div class="card">
            <h3>Apply Rate</h3>
            <div class="metric" id="metric-rate">0%</div>
        </div>
    </div>

    <!-- Charts -->
    <div class="charts">
        <div class="card">
            <h3>Daily Trend (30d)</h3>
            <canvas id="chart-daily"></canvas>
        </div>
        <div class="card">
            <h3>Decision Distribution</h3>
            <canvas id="chart-pie"></canvas>
        </div>
        <div class="card">
            <h3>Top Companies</h3>
            <canvas id="chart-companies"></canvas>
        </div>
    </div>

    <!-- Filters -->
    <div class="filters">
        <input type="text" id="search" placeholder="Search company, title, location..." oninput="filterTable()">
        <select id="filter-decision" onchange="filterTable()">
            <option value="EVALUATED" selected>Evaluated only</option>
            <option value="">All (incl. not evaluated)</option>
            <option value="APPLY">APPLY</option>
            <option value="REVIEW">REVIEW</option>
            <option value="SKIP">SKIP</option>
            <option value="NOT EVALUATED">Not evaluated</option>
        </select>
        <select id="filter-score" onchange="filterTable()">
            <option value="">All Scores</option>
            <option value="80-100">High (80-100)</option>
            <option value="70-79">Medium (70-79)</option>
            <option value="0-69">Low (0-69)</option>
        </select>
        <select id="filter-source" onchange="filterTable()">
            <option value="">All Sources</option>
            <option value="adzuna">Adzuna</option>
            <option value="gmail">Gmail</option>
            <option value="linkedin">LinkedIn</option>
        </select>
        <select id="filter-application" onchange="filterTable()">
            <option value="">All Applications</option>
            <option value="applied">Applied</option>
            <option value="responded">Got a response</option>
            <option value="no_action">No action taken</option>
        </select>
        <button class="btn btn-success" onclick="exportCSV()">Export CSV</button>
    </div>

    <!-- Jobs Table -->
    <div class="card">
        <h3>Jobs</h3>
        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Company</th>
                        <th>Title</th>
                        <th>Location</th>
                        <th>Source</th>
                        <th>Score</th>
                        <th>Decision</th>
                        <th>Application</th>
                        <th>Link</th>
                    </tr>
                </thead>
                <tbody id="jobs-table">
                </tbody>
            </table>
        </div>
        <div class="empty hidden" id="empty-msg">
            <p>No jobs match your filters.</p>
        </div>
    </div>
</div>

<script>
'''


def get_template_tail():
    """Returns the final part of the HTML template (after const JOBS)."""
    return r'''
function getJobField(job, field, fallback="N/A") {
    const j = job.job || {};
    return j[field] || job[field] || fallback;
}

// Job data comes from third-party emails and APIs: always escape before
// inserting into HTML, and only allow http(s) links.
function esc(value) {
    return String(value)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function safeUrl(url) {
    const u = String(url || "").trim();
    return /^https?:\/\//i.test(u) ? u : "";
}

// Mirrors utils.effective_decision on the Python side: thresholds, then
// the hard-blocker lock, then the low-confidence cap (both precomputed
// per job by dashboard.py as _has_blocker / _insufficient).
function getDecision(score, hasBlocker, insufficient, langGap, noText) {
    // No posting text means no score was ever produced. Ranking it, or
    // showing it beside jobs that were actually read, would be a lie.
    if (noText) return "NOT EVALUATED";
    if (hasBlocker) return "SKIP";
    let d = score >= TH_APPLY ? "APPLY" : score >= TH_REVIEW ? "REVIEW" : "SKIP";
    if (d === "APPLY" && (insufficient || langGap)) d = "REVIEW";
    return d;
}

// Status recorded via the "Track Application" workflow takes priority.
// With no tracked record, a REVIEW/APPLY job left untouched for 10+ days
// is treated as implicitly passed on -- no explicit "ignored" click
// required, since requiring one for every skipped job doesn't scale.
const RESPONSE_LABELS = {
    interview_scheduled: "Interview!",
    positive_response: "Positive response",
    rejected: "Rejected",
    awaiting_info: "Info requested",
    responded: "Responded",
};

function getApplicationInfo(job, decision) {
    const app = job._application_status;
    if (app && app.status) {
        if (app.status === "sent") {
            return { label: "Applied", badgeClass: "badge-applied", filterKey: "applied" };
        }
        if (app.status === "recommended") {
            // System picked it, user hasn't applied: distinct from both
            // "Applied" and any recruiter response.
            return { label: "Recommended", badgeClass: "badge-review", filterKey: "recommended" };
        }
        const label = RESPONSE_LABELS[app.status] || RESPONSE_LABELS[app.response_type] || "Responded";
        const badgeClass = app.status === "rejected" ? "badge-rejected" : "badge-interview";
        return { label, badgeClass, filterKey: "responded" };
    }

    if (decision === "APPLY" || decision === "REVIEW") {
        const digestDate = new Date(job._digest_date || "");
        const daysElapsed = isNaN(digestDate) ? 0 : Math.floor((Date.now() - digestDate) / 86400000);
        if (daysElapsed >= 10) {
            return { label: "No action", badgeClass: "badge-noaction", filterKey: "no_action" };
        }
    }

    return { label: "", badgeClass: "", filterKey: "" };
}

function renderTable(jobs) {
    const tbody = document.getElementById("jobs-table");
    const empty = document.getElementById("empty-msg");
    tbody.innerHTML = "";
    
    if (jobs.length === 0) {
        empty.classList.remove("hidden");
        // Metrics describe the filtered view, so they must be zeroed too --
        // they used to keep the previous render's numbers, reading as if
        // they described the (empty) result.
        updateMetrics(jobs);
        return;
    }
    empty.classList.add("hidden");
    
    jobs.sort((a,b) => (b.score||0) - (a.score||0));
    
    jobs.forEach(job => {
        const company = getJobField(job, "company");
        const title = getJobField(job, "title");
        const location = getJobField(job, "location");
        const url = getJobField(job, "url");
        const portal = getJobField(job, "portal", "unknown");
        const score = job.score || 0;
        const decision = getDecision(score, job._has_blocker, job._insufficient, job._lang_gap, job._no_text);
        const date = job._digest_date || "Today";
        
        const badgeClass = decision === "APPLY" ? "badge-apply"
            : decision === "REVIEW" ? "badge-review"
            : decision === "NOT EVALUATED" ? "badge-unknown" : "badge-skip";
        const appInfo = getApplicationInfo(job, decision);

        const link = safeUrl(url);
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${esc(date)}</td>
            <td><strong>${esc(company)}</strong></td>
            <td>${esc(title)}</td>
            <td>${esc(location)}</td>
            <td>${esc(portal)}</td>
            <td class="score">${job._no_text ? "&mdash;" : esc(score)}</td>
            <td><span class="badge ${badgeClass}">${esc(decision)}</span></td>
            <td>${appInfo.label ? `<span class="badge ${appInfo.badgeClass}">${esc(appInfo.label)}</span>` : "-"}</td>
            <td>${link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">View ></a>` : "-"}</td>
        `;
        tbody.appendChild(tr);
    });
    
    updateMetrics(jobs);
}

function filterTable() {
    const search = document.getElementById("search").value.toLowerCase();
    const decision = document.getElementById("filter-decision").value;
    const scoreRange = document.getElementById("filter-score").value;
    const source = document.getElementById("filter-source").value;
    const application = document.getElementById("filter-application").value;

    let filtered = JOBS.filter(job => {
        const company = getJobField(job, "company").toLowerCase();
        const title = getJobField(job, "title").toLowerCase();
        const location = getJobField(job, "location").toLowerCase();
        const portal = getJobField(job, "portal", "unknown").toLowerCase();
        const score = job.score || 0;
        const dec = getDecision(score, job._has_blocker, job._insufficient, job._lang_gap, job._no_text);

        if (search && !company.includes(search) && !title.includes(search) && !location.includes(search)) return false;
        // "Evaluated only" is the default view. Jobs whose posting text was
        // never readable carry no score and cannot be compared with jobs that
        // were actually read, so leading with them buries the system's real
        // judgements. Nothing is hidden: they are one dropdown away, and the
        // metric row below counts them.
        if (decision === "EVALUATED") {
            if (dec === "NOT EVALUATED") return false;
        } else if (decision && dec !== decision) {
            return false;
        }
        if (source && !portal.includes(source)) return false;
        if (application && getApplicationInfo(job, dec).filterKey !== application) return false;
        if (scoreRange) {
            if (scoreRange === "80-100" && score < TH_APPLY) return false;
            if (scoreRange === "70-79" && (score < TH_REVIEW || score >= TH_APPLY)) return false;
            if (scoreRange === "0-69" && score >= TH_REVIEW) return false;
        }
        return true;
    });

    renderTable(filtered);
    updateCharts(filtered);
}

function updateMetrics(jobs) {
    const total = jobs.length;
    const apply = jobs.filter(j => getDecision(j.score||0, j._has_blocker, j._insufficient, j._lang_gap, j._no_text) === "APPLY").length;
    const review = jobs.filter(j => getDecision(j.score||0, j._has_blocker, j._insufficient, j._lang_gap, j._no_text) === "REVIEW").length;
    const skip = jobs.filter(j => getDecision(j.score||0, j._has_blocker, j._insufficient, j._lang_gap, j._no_text) === "SKIP").length;
    const rate = total > 0 ? (apply/total*100).toFixed(1).replace(/\.0$/, "") : "0";
    
    document.getElementById("metric-total").textContent = total;
    document.getElementById("metric-apply").textContent = apply;
    document.getElementById("metric-review").textContent = review;
    document.getElementById("metric-skip").textContent = skip;
    document.getElementById("metric-rate").textContent = rate + "%";
}

function updateCharts(jobs) {
    const daily = {};
    jobs.forEach(j => {
        const d = j._digest_date || "Unknown";
        daily[d] = (daily[d] || 0) + 1;
    });
    const dailyLabels = Object.keys(daily).sort();
    const dailyData = dailyLabels.map(d => daily[d]);
    
    if (window.chartDaily) window.chartDaily.destroy();
    window.chartDaily = new Chart(document.getElementById("chart-daily"), {
        type: "line",
        data: {
            labels: dailyLabels,
            datasets: [{
                label: "Jobs Evaluated",
                data: dailyData,
                borderColor: "#667eea",
                backgroundColor: "rgba(102,126,234,0.1)",
                fill: true,
                tension: 0.3
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
    
    const apply = jobs.filter(j => getDecision(j.score||0, j._has_blocker, j._insufficient, j._lang_gap, j._no_text) === "APPLY").length;
    const review = jobs.filter(j => getDecision(j.score||0, j._has_blocker, j._insufficient, j._lang_gap, j._no_text) === "REVIEW").length;
    const skip = jobs.filter(j => getDecision(j.score||0, j._has_blocker, j._insufficient, j._lang_gap, j._no_text) === "SKIP").length;
    
    if (window.chartPie) window.chartPie.destroy();
    window.chartPie = new Chart(document.getElementById("chart-pie"), {
        type: "doughnut",
        data: {
            labels: ["APPLY", "REVIEW", "SKIP"],
            datasets: [{
                data: [apply, review, skip],
                backgroundColor: ["#32CD32", "#FFA500", "#ff4444"]
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
    
    const companies = {};
    jobs.forEach(j => {
        const c = getJobField(j, "company");
        companies[c] = (companies[c] || 0) + 1;
    });
    const topCompanies = Object.entries(companies).sort((a,b) => b[1]-a[1]).slice(0, 8);
    
    if (window.chartCompanies) window.chartCompanies.destroy();
    window.chartCompanies = new Chart(document.getElementById("chart-companies"), {
        type: "bar",
        data: {
            labels: topCompanies.map(x => x[0]),
            datasets: [{
                label: "Jobs",
                data: topCompanies.map(x => x[1]),
                backgroundColor: "#667eea"
            }]
        },
        options: { responsive: true, maintainAspectRatio: false, indexAxis: "y" }
    });
}

function exportCSV() {
    let filtered = JOBS.filter(job => {
        const search = document.getElementById("search").value.toLowerCase();
        const decision = document.getElementById("filter-decision").value;
        const scoreRange = document.getElementById("filter-score").value;
        const source = document.getElementById("filter-source").value;
        const application = document.getElementById("filter-application").value;

        const company = getJobField(job, "company").toLowerCase();
        const title = getJobField(job, "title").toLowerCase();
        const location = getJobField(job, "location").toLowerCase();
        const portal = getJobField(job, "portal", "unknown").toLowerCase();
        const score = job.score || 0;
        const dec = getDecision(score, job._has_blocker, job._insufficient, job._lang_gap, job._no_text);

        if (search && !company.includes(search) && !title.includes(search) && !location.includes(search)) return false;
        if (decision && dec !== decision) return false;
        if (source && !portal.includes(source)) return false;
        if (application && getApplicationInfo(job, dec).filterKey !== application) return false;
        if (scoreRange) {
            if (scoreRange === "80-100" && score < TH_APPLY) return false;
            if (scoreRange === "70-79" && (score < TH_REVIEW || score >= TH_APPLY)) return false;
            if (scoreRange === "0-69" && score >= TH_REVIEW) return false;
        }
        return true;
    });

    // Escape quotes and neutralise formula injection (=, +, -, @) for Excel
    function csvCell(value) {
        let v = String(value == null ? "" : value).replace(/"/g, '""');
        if (/^[=+\-@]/.test(v)) v = "'" + v;
        return `"${v}"`;
    }

    let csv = "Date,Company,Title,Location,Source,Score,Decision,Application,URL\n";
    filtered.sort((a,b) => (b.score||0) - (a.score||0));
    filtered.forEach(job => {
        const company = getJobField(job, "company");
        const title = getJobField(job, "title");
        const location = getJobField(job, "location");
        const url = getJobField(job, "url");
        const portal = getJobField(job, "portal", "unknown");
        const score = job.score || 0;
        const decision = getDecision(score, job._has_blocker, job._insufficient, job._lang_gap, job._no_text);
        const date = job._digest_date || "Today";
        const application = getApplicationInfo(job, decision).label || "-";
        csv += [csvCell(date), csvCell(company), csvCell(title), csvCell(location), csvCell(portal), score, decision, csvCell(application), csvCell(url)].join(",") + "\n";
    });
    
    const blob = new Blob([csv], {type: "text/csv"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `job-hunt-export-${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
}

function toggleDark() {
    document.body.classList.toggle("dark");
    localStorage.setItem("dark", document.body.classList.contains("dark"));
}

if (localStorage.getItem("dark") === "true") document.body.classList.add("dark");
// Through filterTable, not renderTable(JOBS): the decision filter defaults
// to "Evaluated only", and rendering everything on load would show the
// dropdown claiming one thing while the table showed another.
filterTable();
updateCharts(JOBS);
</script>
</body>
</html>
'''


def generate_dashboard():
    """Generates the complete HTML dashboard."""
    jobs = collect_jobs(days=30)
    app_lookup = load_application_status()
    jobs = attach_application_status(jobs, app_lookup)
    head = get_template_head()
    tail = get_template_tail()

    jobs_json = json.dumps(jobs, ensure_ascii=False, indent=2)
    # Limit size to avoid a giant HTML file
    if len(jobs_json) > 500_000:
        jobs_json = json.dumps(jobs, ensure_ascii=False)
    jobs_json = _js_safe(jobs_json)

    thresholds_js = f"const TH_APPLY = {THRESHOLD_APPLY};\nconst TH_REVIEW = {THRESHOLD_REVIEW};\n"
    html = head + thresholds_js + "const JOBS = " + jobs_json + ";\n" + tail

    os.makedirs(DIGESTS_DIR, exist_ok=True)
    output_path = os.path.join(DIGESTS_DIR, "dashboard.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path, len(jobs)


if __name__ == "__main__":
    path, count = generate_dashboard()
    print(f"Dashboard generated: {path}")
    print(f"Jobs included: {count}")
    print(f"Open in the browser: file://{os.path.abspath(path)}")
