"""
dashboard.py  —  Gera dashboard HTML interativo (versão melhorada)
Features: Chart.js, dark mode, filtros, CSV export, 30-day history
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Paths
DIGESTS_DIR = "digests"
DATA_DIR = "data"
HISTORY_DIR = "data/history"


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_digest_date(filename):
    """Extrai data do nome do arquivo digest_YYYYMMDD_HHMM.json"""
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
    """Coleta avaliações dos últimos N dias a partir dos digests históricos."""
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    all_jobs = []
    seen_urls = set()

    # 1. Digests históricos
    digest_files = sorted(glob.glob(os.path.join(DIGESTS_DIR, "digest_*.json")))
    for dfile in digest_files:
        digest_date = parse_digest_date(dfile)
        if digest_date < cutoff_str and dfile != os.path.join(DIGESTS_DIR, "digest_latest.json"):
            continue

        data = load_json(dfile)
        if not data or not isinstance(data, dict):
            continue

        jobs = data.get("top_jobs", [])
        for ev in jobs:
            job = ev.get("job", ev)
            url = job.get("url", job.get("link", ""))
            key = url or f"{job.get('empresa','')}_{job.get('titulo','')}"
            if key in seen_urls:
                continue
            seen_urls.add(key)

            ev_copy = dict(ev)
            ev_copy["_digest_date"] = digest_date
            all_jobs.append(ev_copy)

    # 2. Avaliações atuais (job_evaluations_latest.json)
    evals = load_json(os.path.join(DIGESTS_DIR, "job_evaluations_latest.json"))
    if evals and isinstance(evals, list):
        today = datetime.now().strftime("%Y-%m-%d")
        for ev in evals:
            job = ev.get("job", ev)
            url = job.get("url", job.get("link", ""))
            key = url or f"{job.get('empresa','')}_{job.get('titulo','')}"
            if key in seen_urls:
                continue
            seen_urls.add(key)
            ev_copy = dict(ev)
            ev_copy["_digest_date"] = today
            all_jobs.append(ev_copy)

    return all_jobs


def get_template_head():
    """Retorna a parte inicial do template HTML (até const JOBS)."""
    return r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunt Dashboard - Carlos Eduardo Duarte Baptista</title>
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
        .dark .badge-skip { background: #b71c1c; color: #ef9a9a; }
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
        <p>Automated job search & evaluation pipeline</p>
    </header>

    <!-- Candidate Profile -->
    <div class="card" style="margin-bottom: 20px;">
        <h3>Candidate Profile</h3>
        <div class="profile">
            <div class="profile-item"><strong>Name</strong>Carlos Eduardo Duarte Baptista</div>
            <div class="profile-item"><strong>Role</strong>Data/Business Analyst</div>
            <div class="profile-item"><strong>Location</strong>Wallisellen, CH</div>
            <div class="profile-item"><strong>Permit</strong>Swiss Work Permit B (valid)</div>
            <div class="profile-item"><strong>Notice</strong>2 weeks</div>
            <div class="profile-item"><strong>Languages</strong>EN (Professional) | PT (Native) | DE (A2)</div>
            <div class="profile-item"><strong>LinkedIn</strong>linkedin.com/in/carlosedbaptista</div>
            <div class="profile-item"><strong>GitHub</strong>github.com/carlosedbaptista</div>
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
            <option value="">All Decisions</option>
            <option value="APPLY">APPLY</option>
            <option value="REVIEW">REVIEW</option>
            <option value="SKIP">SKIP</option>
        </select>
        <select id="filter-score" onchange="filterTable()">
            <option value="">All Scores</option>
            <option value="65-100">High (65-100)</option>
            <option value="45-64">Medium (45-64)</option>
            <option value="0-44">Low (0-44)</option>
        </select>
        <select id="filter-source" onchange="filterTable()">
            <option value="">All Sources</option>
            <option value="adzuna">Adzuna</option>
            <option value="gmail">Gmail</option>
            <option value="linkedin">LinkedIn</option>
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
    """Retorna a parte final do template HTML (após const JOBS)."""
    return r'''
function getJobField(job, field, fallback="N/A") {
    const j = job.job || {};
    return j[field] || job[field] || fallback;
}

function getDecision(score) {
    if (score >= 65) return "APPLY";
    if (score >= 45) return "REVIEW";
    return "SKIP";
}

function renderTable(jobs) {
    const tbody = document.getElementById("jobs-table");
    const empty = document.getElementById("empty-msg");
    tbody.innerHTML = "";
    
    if (jobs.length === 0) {
        empty.classList.remove("hidden");
        return;
    }
    empty.classList.add("hidden");
    
    jobs.sort((a,b) => (b.score||0) - (a.score||0));
    
    jobs.forEach(job => {
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
            <td>${date}</td>
            <td><strong>${company}</strong></td>
            <td>${title}</td>
            <td>${location}</td>
            <td>${portal}</td>
            <td class="score">${score}</td>
            <td><span class="badge ${badgeClass}">${decision}</span></td>
            <td>${url !== "N/A" ? `<a href="${url}" target="_blank">View ></a>` : "-"}</td>
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
    
    let filtered = JOBS.filter(job => {
        const company = getJobField(job, "empresa", getJobField(job, "company")).toLowerCase();
        const title = getJobField(job, "titulo", getJobField(job, "title")).toLowerCase();
        const location = getJobField(job, "localizacao", getJobField(job, "location")).toLowerCase();
        const portal = getJobField(job, "portal", "unknown").toLowerCase();
        const score = job.score || 0;
        const dec = getDecision(score);
        
        if (search && !company.includes(search) && !title.includes(search) && !location.includes(search)) return false;
        if (decision && dec !== decision) return false;
        if (source && !portal.includes(source)) return false;
        if (scoreRange) {
            if (scoreRange === "65-100" && score < 65) return false;
            if (scoreRange === "45-64" && (score < 45 || score >= 65)) return false;
            if (scoreRange === "0-44" && score >= 45) return false;
        }
        return true;
    });
    
    renderTable(filtered);
    updateCharts(filtered);
}

function updateMetrics(jobs) {
    const total = jobs.length;
    const apply = jobs.filter(j => (j.score||0) >= 65).length;
    const review = jobs.filter(j => { const s=j.score||0; return s>=45 && s<65; }).length;
    const skip = jobs.filter(j => (j.score||0) < 45).length;
    const rate = total > 0 ? Math.round(apply/total*100) : 0;
    
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
    
    const apply = jobs.filter(j => (j.score||0) >= 65).length;
    const review = jobs.filter(j => { const s=j.score||0; return s>=45 && s<65; }).length;
    const skip = jobs.filter(j => (j.score||0) < 45).length;
    
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
        const c = getJobField(j, "empresa", getJobField(j, "company"));
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
        
        const company = getJobField(job, "empresa", getJobField(job, "company")).toLowerCase();
        const title = getJobField(job, "titulo", getJobField(job, "title")).toLowerCase();
        const location = getJobField(job, "localizacao", getJobField(job, "location")).toLowerCase();
        const portal = getJobField(job, "portal", "unknown").toLowerCase();
        const score = job.score || 0;
        const dec = getDecision(score);
        
        if (search && !company.includes(search) && !title.includes(search) && !location.includes(search)) return false;
        if (decision && dec !== decision) return false;
        if (source && !portal.includes(source)) return false;
        if (scoreRange) {
            if (scoreRange === "65-100" && score < 65) return false;
            if (scoreRange === "45-64" && (score < 45 || score >= 65)) return false;
            if (scoreRange === "0-44" && score >= 45) return false;
        }
        return true;
    });
    
    let csv = "Date,Company,Title,Location,Source,Score,Decision,URL\n";
    filtered.sort((a,b) => (b.score||0) - (a.score||0));
    filtered.forEach(job => {
        const company = getJobField(job, "empresa", getJobField(job, "company"));
        const title = getJobField(job, "titulo", getJobField(job, "title"));
        const location = getJobField(job, "localizacao", getJobField(job, "location"));
        const url = getJobField(job, "url");
        const portal = getJobField(job, "portal", "unknown");
        const score = job.score || 0;
        const decision = getDecision(score);
        const date = job._digest_date || "Today";
        csv += `"${date}","${company}","${title}","${location}","${portal}",${score},${decision},"${url}"\n`;
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
renderTable(JOBS);
updateCharts(JOBS);
</script>
</body>
</html>
'''


def generate_dashboard():
    """Gera o dashboard HTML completo."""
    jobs = collect_jobs(days=30)
    head = get_template_head()
    tail = get_template_tail()

    jobs_json = json.dumps(jobs, ensure_ascii=False, indent=2)
    # Limita tamanho para evitar HTML gigante
    if len(jobs_json) > 500_000:
        jobs_json = json.dumps(jobs, ensure_ascii=False)

    html = head + "const JOBS = " + jobs_json + ";\n" + tail

    os.makedirs(DIGESTS_DIR, exist_ok=True)
    output_path = os.path.join(DIGESTS_DIR, "dashboard.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path, len(jobs)


if __name__ == "__main__":
    path, count = generate_dashboard()
    print(f"Dashboard gerado: {path}")
    print(f"Jobs incluidos: {count}")
    print(f"Abra no navegador: file://{os.path.abspath(path)}")
