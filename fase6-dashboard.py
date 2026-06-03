#!/usr/bin/env python3
"""
=== PHASE 6: INTERACTIVE DASHBOARD ===
Generates an interactive HTML dashboard with Chart.js graphs, filters,
search, 30-day history, CSV export, and auto-filled candidate profile.
All output in English.
"""
import os
import json
import glob
import subprocess
from datetime import datetime, timezone, timedelta

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

def wf(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERROR: Run this script from the repo root directory"); exit(1)

print("=== PHASE 6: INTERACTIVE DASHBOARD ===\n")

# 1. Load candidate profile
CANDIDATE_PATH = f"{REPO}/config/candidate_profile.json"
candidate = {}
if os.path.exists(CANDIDATE_PATH):
    with open(CANDIDATE_PATH, "r", encoding="utf-8") as f:
        candidate = json.load(f)

# 2. Load evaluation history (last 30 days)
def load_history(days=30):
    history = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Load all digest files from last N days
    for digest_file in sorted(glob.glob(f"{REPO}/digests/digest_*.json")):
        try:
            with open(digest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            gen_at = data.get("generated_at", "")
            if gen_at and gen_at >= cutoff.isoformat():
                for job in data.get("top_jobs", []):
                    job["_digest_date"] = gen_at[:10]
                    history.append(job)
        except (json.JSONDecodeError, IOError):
            continue
    
    # Also load current evaluations
    eval_path = f"{REPO}/digests/job_evaluations_latest.json"
    if os.path.exists(eval_path):
        try:
            with open(eval_path, "r", encoding="utf-8") as f:
                jobs = json.load(f)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for job in jobs:
                job["_digest_date"] = today
                history.append(job)
        except (json.JSONDecodeError, IOError):
            pass
    
    return history

history = load_history(30)

# 3. Generate the dashboard HTML
DASHBOARD_HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunt Dashboard - {candidate.get("name", "Candidate")}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {{
            --bg: #f5f5f5; --card: #fff; --text: #333; --muted: #666;
            --accent: #667eea; --accent2: #764ba2; --success: #32CD32;
            --warning: #FFA500; --danger: #ff4444; --border: #e0e0e0;
        }}
        body.dark {{
            --bg: #1a1a2e; --card: #16213e; --text: #eee; --muted: #aaa;
            --border: #2a2a4a;
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg); color: var(--text); transition: background 0.3s, color 0.3s;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
            color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px;
        }}
        header h1 {{ font-size: 28px; margin-bottom: 5px; }}
        header p {{ opacity: 0.9; font-size: 14px; }}
        .toggle-btn {{
            float: right; background: rgba(255,255,255,0.2); border: none;
            color: white; padding: 8px 16px; border-radius: 6px; cursor: pointer;
        }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .card {{
            background: var(--card); border-radius: 10px; padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08); border: 1px solid var(--border);
        }}
        .card h3 {{ font-size: 14px; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .metric {{ font-size: 36px; font-weight: 700; color: var(--accent); }}
        .metric.green {{ color: var(--success); }}
        .metric.orange {{ color: var(--warning); }}
        .metric.red {{ color: var(--danger); }}
        .filters {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }}
        .filters input, .filters select {{
            padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px;
            background: var(--card); color: var(--text); font-size: 14px;
        }}
        .filters input {{ flex: 1; min-width: 200px; }}
        .btn {{
            padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer;
            font-size: 14px; font-weight: 600; transition: opacity 0.2s;
        }}
        .btn:hover {{ opacity: 0.85; }}
        .btn-primary {{ background: var(--accent); color: white; }}
        .btn-success {{ background: var(--success); color: white; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 12px; font-size: 12px; text-transform: uppercase; color: var(--muted); border-bottom: 2px solid var(--border); }}
        td {{ padding: 12px; border-bottom: 1px solid var(--border); }}
        tr:hover {{ background: rgba(102,126,234,0.05); }}
        .badge {{ padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
        .badge-apply {{ background: #e8f5e9; color: #2e7d32; }}
        .dark .badge-apply {{ background: #1b5e20; color: #a5d6a7; }}
        .badge-review {{ background: #fff3e0; color: #ef6c00; }}
        .dark .badge-review {{ background: #e65100; color: #ffcc80; }}
        .badge-skip {{ background: #ffebee; color: #c62828; }}
        .dark .badge-skip {{ background: #b71c1c; color: #ef9a9a; }}
        .score {{ font-weight: 700; }}
        .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .charts .card {{ padding: 15px; }}
        canvas {{ max-height: 250px; }}
        .profile {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }}
        .profile-item {{ font-size: 13px; color: var(--muted); }}
        .profile-item strong {{ color: var(--text); display: block; margin-bottom: 2px; }}
        .empty {{ text-align: center; padding: 60px 20px; color: var(--muted); }}
        .hidden {{ display: none; }}
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
            .charts {{ grid-template-columns: 1fr; }}
            .filters {{ flex-direction: column; }}
            th, td {{ font-size: 13px; padding: 8px; }}
        }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <button class="toggle-btn" onclick="toggleDark()">Dark Mode</button>
        <h1>Job Hunt Dashboard</h1>
        <p>Automated job search & evaluation pipeline</p>
    </header>

    <!-- Candidate Profile -->
    <div class="card" style="margin-bottom: 20px;">
        <h3>Candidate Profile</h3>
        <div class="profile">
            <div class="profile-item"><strong>Name</strong>{candidate.get("name", "N/A")}</div>
            <div class="profile-item"><strong>Role</strong>{candidate.get("role", "N/A")}</div>
            <div class="profile-item"><strong>Location</strong>{candidate.get("location", "N/A")}</div>
            <div class="profile-item"><strong>Permit</strong>{candidate.get("permit", "N/A")}</div>
            <div class="profile-item"><strong>Languages</strong>{", ".join(f"{k.upper()}:{v}" for k,v in candidate.get("languages", {}).items()) or "N/A"}</div>
            <div class="profile-item"><strong>Skills</strong>{", ".join(candidate.get("skills", [])) or "N/A"}</div>
            <div class="profile-item"><strong>Email</strong>{candidate.get("email", "N/A")}</div>
            <div class="profile-item"><strong>Phone</strong>{candidate.get("phone", "N/A")}</div>
            <div class="profile-item"><strong>LinkedIn</strong><a href="https://{candidate.get("linkedin", "#")}" target="_blank">{candidate.get("linkedin", "N/A")}</a></div>
            <div class="profile-item"><strong>Status</strong>{candidate.get("work_status", "N/A")}</div>
        </div>
        <p style="margin-top:10px;font-size:12px;color:var(--muted);">Edit <code>config/candidate_profile.json</code> to update your profile.</p>
    </div>

    <!-- Metrics -->
    <div class="grid">
        <div class="card">
            <h3>Total Evaluated (30d)</h3>
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
            <h3>Daily Jobs (Last 30 Days)</h3>
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
        <input type="text" id="search" placeholder="Search company, title, or location..." oninput="filterTable()">
        <select id="filter-decision" onchange="filterTable()">
            <option value="">All Decisions</option>
            <option value="APPLY">APPLY</option>
            <option value="REVIEW">REVIEW</option>
            <option value="SKIP">SKIP</option>
        </select>
        <select id="filter-score" onchange="filterTable()">
            <option value="">All Scores</option>
            <option value="65-100">65+ (APPLY)</option>
            <option value="45-64">45-64 (REVIEW)</option>
            <option value="0-44">Below 45 (SKIP)</option>
        </select>
        <select id="filter-source" onchange="filterTable()">
            <option value="">All Sources</option>
            <option value="adzuna">Adzuna</option>
            <option value="linkedin">LinkedIn</option>
            <option value="email">Email</option>
        </select>
        <button class="btn btn-success" onclick="exportCSV()">Export CSV</button>
    </div>

    <!-- Table -->
    <div class="card">
        <h3>All Evaluated Jobs</h3>
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
const JOBS = {json.dumps(history, ensure_ascii=False)};

function getJobField(job, field, fallback="N/A") {{
    const j = job.job || {{}};
    return j[field] || job[field] || fallback;
}}

function getDecision(score) {{
    if (score >= 65) return "APPLY";
    if (score >= 45) return "REVIEW";
    return "SKIP";
}}

function renderTable(jobs) {{
    const tbody = document.getElementById("jobs-table");
    const empty = document.getElementById("empty-msg");
    tbody.innerHTML = "";
    
    if (jobs.length === 0) {{
        empty.classList.remove("hidden");
        return;
    }}
    empty.classList.add("hidden");
    
    // Sort by score desc
    jobs.sort((a,b) => (b.score||0) - (a.score||0));
    
    jobs.forEach(job => {{
        const company = getJobField(job, "empresa", getJobField(job, "company"));
        const title = getJobField(job, "titulo", getJobField(job, "title"));
        const location = getJobField(job, "localizacao", getJobField(job, "location"));
        const url = getJobField(job, "url");
        const portal = getJobField(job, "portal", "unknown");
        const score = job.score || 0;
        const decision = getDecision(score);
        const date = job._digest_date || "Today";
        
        const badgeClass = decision === "APPLY" ? "badge-apply" : decision === "REVIEW" ? "badge-review" : "badge-skip";
        
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${{date}}</td>
            <td><strong>${{company}}</strong></td>
            <td>${{title}}</td>
            <td>${{location}}</td>
            <td>${{portal}}</td>
            <td class="score">${{score}}</td>
            <td><span class="badge ${{badgeClass}}">${{decision}}</span></td>
            <td>${{url !== "N/A" ? `<a href="${{url}}" target="_blank">View &gt;</a>` : "-"}}</td>
        `;
        tbody.appendChild(tr);
    }});
    
    updateMetrics(jobs);
}}

function filterTable() {{
    const search = document.getElementById("search").value.toLowerCase();
    const decision = document.getElementById("filter-decision").value;
    const scoreRange = document.getElementById("filter-score").value;
    const source = document.getElementById("filter-source").value;
    
    let filtered = JOBS.filter(job => {{
        const company = getJobField(job, "empresa", getJobField(job, "company")).toLowerCase();
        const title = getJobField(job, "titulo", getJobField(job, "title")).toLowerCase();
        const location = getJobField(job, "localizacao", getJobField(job, "location")).toLowerCase();
        const portal = getJobField(job, "portal", "unknown").toLowerCase();
        const score = job.score || 0;
        const dec = getDecision(score);
        
        if (search && !company.includes(search) && !title.includes(search) && !location.includes(search)) return false;
        if (decision && dec !== decision) return false;
        if (source && !portal.includes(source)) return false;
        if (scoreRange) {{
            if (scoreRange === "65-100" && score < 65) return false;
            if (scoreRange === "45-64" && (score < 45 || score >= 65)) return false;
            if (scoreRange === "0-44" && score >= 45) return false;
        }}
        return true;
    }});
    
    renderTable(filtered);
    updateCharts(filtered);
}}

function updateMetrics(jobs) {{
    const total = jobs.length;
    const apply = jobs.filter(j => (j.score||0) >= 65).length;
    const review = jobs.filter(j => {{ const s=j.score||0; return s>=45 && s<65; }}).length;
    const skip = jobs.filter(j => (j.score||0) < 45).length;
    const rate = total > 0 ? Math.round(apply/total*100) : 0;
    
    document.getElementById("metric-total").textContent = total;
    document.getElementById("metric-apply").textContent = apply;
    document.getElementById("metric-review").textContent = review;
    document.getElementById("metric-skip").textContent = skip;
    document.getElementById("metric-rate").textContent = rate + "%";
}}

function updateCharts(jobs) {{
    // Daily chart
    const daily = {{}};
    jobs.forEach(j => {{
        const d = j._digest_date || "Unknown";
        daily[d] = (daily[d] || 0) + 1;
    }});
    const dailyLabels = Object.keys(daily).sort();
    const dailyData = dailyLabels.map(d => daily[d]);
    
    if (window.chartDaily) window.chartDaily.destroy();
    window.chartDaily = new Chart(document.getElementById("chart-daily"), {{
        type: "line",
        data: {{
            labels: dailyLabels,
            datasets: [{{
                label: "Jobs Evaluated",
                data: dailyData,
                borderColor: "#667eea",
                backgroundColor: "rgba(102,126,234,0.1)",
                fill: true,
                tension: 0.3
            }}]
        }},
        options: {{ responsive: true, maintainAspectRatio: false }}
    }});
    
    // Pie chart
    const apply = jobs.filter(j => (j.score||0) >= 65).length;
    const review = jobs.filter(j => {{ const s=j.score||0; return s>=45 && s<65; }}).length;
    const skip = jobs.filter(j => (j.score||0) < 45).length;
    
    if (window.chartPie) window.chartPie.destroy();
    window.chartPie = new Chart(document.getElementById("chart-pie"), {{
        type: "doughnut",
        data: {{
            labels: ["APPLY", "REVIEW", "SKIP"],
            datasets: [{{
                data: [apply, review, skip],
                backgroundColor: ["#32CD32", "#FFA500", "#ff4444"]
            }}]
        }},
        options: {{ responsive: true, maintainAspectRatio: false }}
    }});
    
    // Companies chart
    const companies = {{}};
    jobs.forEach(j => {{
        const c = getJobField(j, "empresa", getJobField(j, "company"));
        companies[c] = (companies[c] || 0) + 1;
    }});
    const topCompanies = Object.entries(companies).sort((a,b) => b[1]-a[1]).slice(0, 8);
    
    if (window.chartCompanies) window.chartCompanies.destroy();
    window.chartCompanies = new Chart(document.getElementById("chart-companies"), {{
        type: "bar",
        data: {{
            labels: topCompanies.map(x => x[0]),
            datasets: [{{
                label: "Jobs",
                data: topCompanies.map(x => x[1]),
                backgroundColor: "#667eea"
            }}]
        }},
        options: {{ responsive: true, maintainAspectRatio: false, indexAxis: "y" }}
    }});
}}

function exportCSV() {{
    const search = document.getElementById("search").value.toLowerCase();
    const decision = document.getElementById("filter-decision").value;
    const scoreRange = document.getElementById("filter-score").value;
    const source = document.getElementById("filter-source").value;
    
    let filtered = JOBS.filter(job => {{
        const company = getJobField(job, "empresa", getJobField(job, "company")).toLowerCase();
        const title = getJobField(job, "titulo", getJobField(job, "title")).toLowerCase();
        const location = getJobField(job, "localizacao", getJobField(job, "location")).toLowerCase();
        const portal = getJobField(job, "portal", "unknown").toLowerCase();
        const score = job.score || 0;
        const dec = getDecision(score);
        
        if (search && !company.includes(search) && !title.includes(search) && !location.includes(search)) return false;
        if (decision && dec !== decision) return false;
        if (source && !portal.includes(source)) return false;
        if (scoreRange) {{
            if (scoreRange === "65-100" && score < 65) return false;
            if (scoreRange === "45-64" && (score < 45 || score >= 65)) return false;
            if (scoreRange === "0-44" && score >= 45) return false;
        }}
        return true;
    }});
    
    let csv = "Date,Company,Title,Location,Source,Score,Decision,URL\\n";
    filtered.sort((a,b) => (b.score||0) - (a.score||0));
    filtered.forEach(job => {{
        const company = getJobField(job, "empresa", getJobField(job, "company"));
        const title = getJobField(job, "titulo", getJobField(job, "title"));
        const location = getJobField(job, "localizacao", getJobField(job, "location"));
        const url = getJobField(job, "url");
        const portal = getJobField(job, "portal", "unknown");
        const score = job.score || 0;
        const decision = getDecision(score);
        const date = job._digest_date || "Today";
        csv += `"${{date}}","${{company}}","${{title}}","${{location}}","${{portal}}",${{score}},${{decision}},"${{url}}"\\n`;
    }});
    
    const blob = new Blob([csv], {{type: "text/csv"}});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `job-hunt-export-${{new Date().toISOString().split("T")[0]}}.csv`;
    a.click();
}}

function toggleDark() {{
    document.body.classList.toggle("dark");
    localStorage.setItem("dark", document.body.classList.contains("dark"));
}}

// Init
if (localStorage.getItem("dark") === "true") document.body.classList.add("dark");
renderTable(JOBS);
updateCharts(JOBS);
</script>
</body>
</html>
'''

# Save dashboard
DASHBOARD_PATH = f"{REPO}/digests/dashboard.html"
with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
    f.write(DASHBOARD_HTML)

print(f"[OK] digests/dashboard.html -> generated ({len(DASHBOARD_HTML)} chars)")
print(f"     Loaded {len(history)} jobs from last 30 days")
print(f"     Candidate profile: {candidate.get('name', 'N/A')}")

# 4. Commit
run("git add -A")
ok, _, err = run('git commit -m "feat: interactive dashboard with Chart.js, filters, 30d history, CSV export"')
if ok:
    print("\n[OK] Commit successful! Next: git push origin main")
else:
    print(f"\n[!] Commit issue: {err[:200]}")

print("\n=== PHASE 6 COMPLETE ===")
print("Dashboard features:")
print("  - Candidate profile auto-filled from config/candidate_profile.json")
print("  - 4 metric cards: Total, APPLY, REVIEW, SKIP, Apply Rate")
print("  - 3 Chart.js graphs: Daily trend, Decision pie, Top companies bar")
print("  - Filters: Search text, Decision, Score range, Source")
print("  - Export CSV button")
print("  - Dark mode toggle")
print("  - Responsive design (mobile-friendly)")
print("View at: https://carlosedbaptista.github.io/job-hunt-pipeline/digests/dashboard.html")
