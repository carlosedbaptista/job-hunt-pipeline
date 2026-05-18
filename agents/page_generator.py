"""
page_generator.py  —  Generates a GitHub Pages HTML dashboard from digest_latest.json
Saves to docs/index.html so GitHub Pages can serve it publicly.
"""

import json
import os
from datetime import datetime


def load_digest():
    digest_file = "digests/digest_latest.json"
    if not os.path.exists(digest_file):
        return None
    with open(digest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def score_color(score: int) -> str:
    if score >= 65:
        return "#22c55e"
    if score >= 45:
        return "#f59e0b"
    return "#ef4444"


def score_label(score: int, recommendation: str) -> str:
    if recommendation == "DO NOT APPLY":
        return "DO NOT APPLY"
    if score >= 65:
        return "APPLY"
    if score >= 45:
        return "REVIEW"
    return "UNCERTAIN"


def render_tag_list(items: list, color: str) -> str:
    if not items:
        return ""
    tags = "".join(
        f'<span style="display:inline-block;background:{color}18;color:{color};'
        f'border:1px solid {color}40;border-radius:4px;padding:2px 8px;'
        f'font-size:12px;margin:2px 4px 2px 0;">{item}</span>'
        for item in items
    )
    return tags


def generate_html(digest: dict) -> str:
    top_jobs = digest.get("top_jobs", [])
    total = digest.get("total_evaluated", 0)
    generated_at = digest.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(generated_at)
        date_str = dt.strftime("%B %d, %Y at %H:%M")
    except Exception:
        date_str = generated_at[:16]

    apply_count = sum(1 for j in top_jobs if j.get("score", 0) >= 65)
    review_count = sum(1 for j in top_jobs if 45 <= j.get("score", 0) < 65)
    uncertain_count = sum(1 for j in top_jobs if j.get("score", 0) < 45)

    job_cards = ""
    for i, job_eval in enumerate(top_jobs, 1):
        score = job_eval.get("score", 0)
        rec = job_eval.get("recommendation", "UNCERTAIN")
        label = score_label(score, rec)
        color = score_color(score)
        job = job_eval.get("job", {})

        empresa = job.get("empresa") or "Unknown"
        titulo = job.get("titulo") or "No title"
        localizacao = job.get("localizacao") or "Unknown"
        portal = job.get("portal") or ""
        url = job.get("url") or ""

        summary = job_eval.get("job_summary_for_user") or ""
        angle = job_eval.get("suggested_angle") or ""
        match_points = job_eval.get("key_match_points") or []
        red_flags = job_eval.get("red_flags") or []
        deal_breakers = job_eval.get("deal_breakers_found") or []

        tech = job_eval.get("technical_fit", {})
        ctx = job_eval.get("contextual_fit", {})
        opp = job_eval.get("opportunity_fit", {})

        view_link = (
            f'<a href="{url}" target="_blank" style="display:inline-block;'
            f'margin-top:12px;color:#6366f1;font-size:13px;text-decoration:none;'
            f'font-weight:600;">View job listing →</a>'
            if url else ""
        )

        job_cards += f"""
        <div style="background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;
                    box-shadow:0 1px 3px rgba(0,0,0,0.08);border-left:4px solid {color};">

          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
            <div>
              <div style="font-size:12px;color:#94a3b8;font-weight:600;letter-spacing:.05em;
                          text-transform:uppercase;margin-bottom:4px;">#{i} · {portal}</div>
              <div style="font-size:18px;font-weight:700;color:#1e293b;">{empresa}</div>
              <div style="font-size:14px;color:#475569;margin-top:2px;">{titulo}</div>
              <div style="font-size:13px;color:#94a3b8;margin-top:2px;">📍 {localizacao}</div>
            </div>
            <div style="text-align:right;">
              <div style="font-size:28px;font-weight:800;color:{color};">{score}<span style="font-size:14px;font-weight:400;color:#94a3b8;">/100</span></div>
              <div style="display:inline-block;background:{color};color:#fff;border-radius:6px;
                          padding:3px 10px;font-size:11px;font-weight:700;letter-spacing:.05em;">{label}</div>
            </div>
          </div>

          <div style="margin-top:16px;display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
            <div style="background:#f8fafc;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;">Technical</div>
              <div style="font-size:20px;font-weight:700;color:#1e293b;">{tech.get("score",0)}<span style="font-size:11px;color:#94a3b8;">/40</span></div>
            </div>
            <div style="background:#f8fafc;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;">Contextual</div>
              <div style="font-size:20px;font-weight:700;color:#1e293b;">{ctx.get("score",0)}<span style="font-size:11px;color:#94a3b8;">/35</span></div>
            </div>
            <div style="background:#f8fafc;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;">Opportunity</div>
              <div style="font-size:20px;font-weight:700;color:#1e293b;">{opp.get("score",0)}<span style="font-size:11px;color:#94a3b8;">/25</span></div>
            </div>
          </div>

          {"<p style='margin:14px 0 6px;font-size:13px;color:#475569;line-height:1.6;'>" + summary + "</p>" if summary else ""}

          {"<div style='margin-top:12px;'><div style='font-size:11px;font-weight:700;color:#22c55e;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;'>Highlights</div>" + render_tag_list(match_points, "#22c55e") + "</div>" if match_points else ""}

          {"<div style='margin-top:10px;'><div style='font-size:11px;font-weight:700;color:#f59e0b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;'>Red Flags</div>" + render_tag_list(red_flags, "#f59e0b") + "</div>" if red_flags else ""}

          {"<div style='margin-top:10px;'><div style='font-size:11px;font-weight:700;color:#ef4444;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;'>Deal Breakers</div>" + render_tag_list(deal_breakers, "#ef4444") + "</div>" if deal_breakers else ""}

          {"<div style='margin-top:12px;background:#f0f4ff;border-radius:6px;padding:10px 12px;'><div style='font-size:11px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;'>Suggested Angle</div><div style='font-size:13px;color:#374151;line-height:1.5;'>" + angle + "</div></div>" if angle else ""}

          {view_link}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Hunt Dashboard — Carlos Baptista</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f1f5f9; color: #1e293b; padding: 20px; }}
    .container {{ max-width: 760px; margin: 0 auto; }}
    @media (max-width: 600px) {{
      body {{ padding: 12px; }}
      .stats-grid {{ grid-template-columns: repeat(2, 1fr) !important; }}
    }}
  </style>
</head>
<body>
  <div class="container">

    <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;
                border-radius:14px;padding:28px;margin-bottom:24px;">
      <div style="font-size:22px;font-weight:800;">📊 Job Hunt Dashboard</div>
      <div style="font-size:13px;opacity:.85;margin-top:6px;">Carlos Baptista · Wallisellen, Zürich</div>
      <div style="font-size:12px;opacity:.7;margin-top:4px;">Updated: {date_str}</div>
    </div>

    <div class="stats-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;">
      <div style="background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
        <div style="font-size:24px;font-weight:800;color:#6366f1;">{total}</div>
        <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;margin-top:4px;">Evaluated</div>
      </div>
      <div style="background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
        <div style="font-size:24px;font-weight:800;color:#22c55e;">{apply_count}</div>
        <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;margin-top:4px;">Apply</div>
      </div>
      <div style="background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
        <div style="font-size:24px;font-weight:800;color:#f59e0b;">{review_count}</div>
        <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;margin-top:4px;">Review</div>
      </div>
      <div style="background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
        <div style="font-size:24px;font-weight:800;color:#ef4444;">{uncertain_count}</div>
        <div style="font-size:11px;color:#94a3b8;font-weight:600;text-transform:uppercase;margin-top:4px;">Uncertain</div>
      </div>
    </div>

    <div style="font-size:16px;font-weight:700;color:#1e293b;margin-bottom:14px;">
      Top Jobs — Sorted by Fit Score
    </div>

    {job_cards}

    <div style="text-align:center;padding:20px;font-size:12px;color:#94a3b8;">
      Job Hunt Pipeline · Auto-updated daily · Carlos Baptista
    </div>

  </div>
</body>
</html>"""


def save_page(html: str):
    os.makedirs("docs", exist_ok=True)
    path = "docs/index.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


if __name__ == "__main__":
    import sys

    digest = load_digest()
    if not digest:
        print("❌ No digest found. Run digest_generator.py first.")
        sys.exit(1)

    html = generate_html(digest)
    path = save_page(html)
    print(f"✅ Dashboard saved → {path}")
    print(f"   Jobs shown: {len(digest.get('top_jobs', []))}")
