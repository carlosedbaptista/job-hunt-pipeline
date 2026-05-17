"""
analytics_engine.py  —  Analyses pipeline data
Generates insights by industry, ATS platform, and job type.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = "tracker/jobs.db"


def get_db_connection():
    return sqlite3.connect(DB_PATH)


# ═════════════════════════════════════════════════════════════════════════════
# DATA CLASSIFICATION
# ═════════════════════════════════════════════════════════════════════════════

INDUSTRY_KEYWORDS = {
    "tech": ["software", "tech", "it", "digital", "ai", "machine learning", "data"],
    "finance": ["bank", "finance", "investment", "trading", "fintech", "insurance"],
    "pharma": ["pharma", "biotech", "medical", "health", "drug", "clinical"],
    "manufacturing": ["manufacturing", "industrial", "production", "supply chain"],
    "retail": ["retail", "ecommerce", "commerce", "shop", "store"],
    "consulting": ["consulting", "strategy", "management", "advisory"],
    "government": ["government", "public", "state", "federal", "municipal"],
    "other": [],
}

JOB_TYPE_KEYWORDS = {
    "data_analyst": ["data analyst", "analytics", "bi analyst", "business intelligence"],
    "business_analyst": ["business analyst", "product analyst", "operations"],
    "ai_ml": ["ai", "machine learning", "ml engineer", "ai engineer", "nlp"],
    "reporting": ["reporting", "dashboard", "reporting analyst"],
    "data_engineer": ["data engineer", "etl", "data pipeline"],
    "other": [],
}

ATS_KEYWORDS = {
    "workday": ["workday"],
    "greenhouse": ["greenhouse"],
    "lever": ["lever"],
    "talentsoft": ["talentsoft"],
    "successfactors": ["successfactors"],
    "linkedin": ["linkedin"],
    "indeed": ["indeed"],
    "generic": [],
}


def classify_text(text: str, keywords_dict: dict) -> str:
    """Classifies text by matching against a keyword dictionary."""
    text_lower = text.lower()
    for category, keywords in keywords_dict.items():
        if category == "other":
            continue
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return category
    return "other"


def classify_application(app: dict) -> dict:
    """Classifies an application across industry, job type, and ATS dimensions."""
    empresa = app.get("empresa", "")
    titulo = app.get("titulo", "")

    return {
        "industry": classify_text(empresa + " " + titulo, INDUSTRY_KEYWORDS),
        "job_type": classify_text(titulo, JOB_TYPE_KEYWORDS),
        "ats": classify_text(empresa, ATS_KEYWORDS),
    }


# ═════════════════════════════════════════════════════════════════════════════
# DIMENSION ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def get_all_applications():
    """Fetches all applications from the database."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    apps = conn.execute(
        "SELECT * FROM applications ORDER BY date_applied DESC"
    ).fetchall()

    conn.close()
    return [dict(app) for app in apps]


def analyze_by_dimension(apps: list, dimension: str) -> dict:
    """Analyses response rate grouped by the given dimension (industry, job_type, ats)."""
    classified = defaultdict(lambda: {"total": 0, "responded": 0, "rejections": 0})

    for app in apps:
        classification = classify_application(app)
        category = classification.get(dimension, "other")

        classified[category]["total"] += 1

        if app.get("response_type"):
            classified[category]["responded"] += 1
            if app.get("status") == "rejected":
                classified[category]["rejections"] += 1

    results = {}
    for category, stats in classified.items():
        total = stats["total"]
        responded = stats["responded"]
        rejection_rate = (stats["rejections"] / responded * 100) if responded > 0 else 0
        response_rate = (responded / total * 100) if total > 0 else 0

        results[category] = {
            "total_applications": total,
            "total_responses": responded,
            "response_rate_percent": round(response_rate, 1),
            "rejection_rate_percent": round(rejection_rate, 1),
        }

    return results


def analyze_response_time(apps: list) -> dict:
    """Analyses average response time across all applications."""
    response_times = {"avg_days": 0, "min_days": 0, "max_days": 0}

    times = []
    for app in apps:
        if app.get("response_date") and app.get("date_applied"):
            try:
                applied = datetime.fromisoformat(app["date_applied"])
                responded = datetime.fromisoformat(app["response_date"])
                days = (responded - applied).days
                times.append(days)
            except:
                pass

    if times:
        response_times["avg_days"] = round(sum(times) / len(times), 1)
        response_times["min_days"] = min(times)
        response_times["max_days"] = max(times)

    return response_times


def generate_analytics_report(apps: list) -> dict:
    """Generates a full analytics report."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_applications": len(apps),
        "dimensions": {
            "by_industry": analyze_by_dimension(apps, "industry"),
            "by_job_type": analyze_by_dimension(apps, "job_type"),
            "by_ats": analyze_by_dimension(apps, "ats"),
        },
        "response_time": analyze_response_time(apps),
    }

    total_responses = sum(1 for a in apps if a.get("response_type"))
    report["overall_metrics"] = {
        "total_applications": len(apps),
        "total_responses": total_responses,
        "overall_response_rate": round(
            (total_responses / len(apps) * 100) if len(apps) > 0 else 0, 1
        ),
    }

    return report


def get_recommendations(report: dict) -> list:
    """Generates recommendations based on the analytics report."""
    recommendations = []

    by_industry = report["dimensions"]["by_industry"]
    if by_industry:
        best_industry = max(by_industry.items(), key=lambda x: x[1]["response_rate_percent"])
        recommendations.append(
            f"🎯 Focus on {best_industry[0]}: {best_industry[1]['response_rate_percent']}% response rate"
        )

    by_ats = report["dimensions"]["by_ats"]
    if by_ats:
        best_ats = max(by_ats.items(), key=lambda x: x[1]["response_rate_percent"])
        recommendations.append(
            f"🏢 Most responsive platform: {best_ats[0]} ({best_ats[1]['response_rate_percent']}%)"
        )

    by_job = report["dimensions"]["by_job_type"]
    if by_job:
        best_job = max(by_job.items(), key=lambda x: x[1]["response_rate_percent"])
        recommendations.append(
            f"💼 Best-fit role type: {best_job[0]} ({best_job[1]['response_rate_percent']}%)"
        )

    return recommendations


if __name__ == "__main__":
    print("Analysing data...\n")

    apps = get_all_applications()

    if not apps:
        print("❌ No applications recorded yet")
        exit(1)

    report = generate_analytics_report(apps)

    print(json.dumps(report, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70 + "\n")

    recommendations = get_recommendations(report)
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec}")
