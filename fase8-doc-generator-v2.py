#!/usr/bin/env python3
"""
=== PHASE 8v2: TAILORED CV + COVER LETTER GENERATOR ===
AI-tailored Profile Summary per job, photo support, skill reordering,
1-page layout, Cover Letter with pipeline citation.
"""
import os
import subprocess

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

print("=== PHASE 8v2: TAILORED CV + COVER LETTER ===\n")

# 1. Create structured candidate profile with experience, education, skill variants
wf(f"{REPO}/config/candidate_profile.json", r"""{
  "name": "Carlos Eduardo Duarte Baptista",
  "address": "Alte Winterthurerstrasse 107, 8304 Wallisellen",
  "phone": "+41 78 261 34 74",
  "email": "carlosedbaptista@gmail.com",
  "email_icloud": "carlos.baptistaa@icloud.com",
  "linkedin": "linkedin.com/in/carlosedbaptista",
  "github": "github.com/carlosedbaptista",
  "dob": "10.03.1999",
  "nationality": "Brazilian",
  "permit": "Swiss Work Permit B (valid)",
  "relocation_date": "April 2025",
  "role": "Data/Business Analyst",
  "location": "Wallisellen, CH",
  "notice_period": "2 weeks",
  "photo_path": "config/photo.jpg",
  "skills": {
    "technical_default": [
      "Python (academic + applied -- multi-agent pipeline project)",
      "JavaScript / Node.js / SuiteScript / HTML",
      "AI Tools & APIs (Claude API, ChatGPT, Kimi)",
      "Power BI",
      "Data Modeling",
      "Jira",
      "MS Office (Excel, PowerPoint, SharePoint, OneNote)",
      "Oracle NetSuite"
    ],
    "technical_data_focused": [
      "Power BI",
      "SharePoint",
      "MS Office (Excel, PowerPoint, OneNote)",
      "Python (academic + applied)",
      "JavaScript / Node.js / SuiteScript / HTML",
      "Data Modeling",
      "AI Tools (Claude, ChatGPT, Gemini)",
      "Jira",
      "Oracle NetSuite"
    ],
    "technical_ai_focused": [
      "Python (academic + applied -- multi-agent pipeline project)",
      "JavaScript / Node.js / SuiteScript / HTML",
      "AI Tools & APIs (Claude API, ChatGPT, Kimi)",
      "Data Modeling",
      "Power BI",
      "Jira",
      "MS Office (Excel, PowerPoint, SharePoint, OneNote)",
      "Oracle NetSuite"
    ],
    "communication": [
      "Change management communication",
      "Presentation design",
      "Workshop facilitation support"
    ],
    "certifications": [
      "Google AI Essentials (2025)",
      "GA4 Certification (2026)",
      "Anthropic Claude 101, Claude Code 101, Claude Cowork, AI Fluency (2026)"
    ]
  },
  "experience": [
    {
      "period": "06.2025 -- Present",
      "title": "Digital Marketing & Analytics Associate (Pro Bono, 20h/week)",
      "company": "netzdenker.com -- Wallisellen, Switzerland",
      "bullets": [
        "Analysed Google Analytics 4 and Campaign Manager 360 data to extract insights and optimise marketing campaign performance; produced structured documentation to support strategic decision-making",
        "Used Python, JavaScript, HTML, and AI tools (Claude, ChatGPT) to overhaul the company website, adding new functionalities that increased page views and clicks by 35%",
        "Coordinated cross-functional operational workflows using AI-assisted tools, maintaining documentation and tracking deliverables across marketing and analytics initiatives"
      ]
    },
    {
      "period": "06.2025 -- Present",
      "title": "Operations Support Associate (Freelancer)",
      "company": "Coople (Schweiz) AG -- Switzerland",
      "bullets": [
        "Customer-facing service and operations support in dynamic event environments",
        "Adapted quickly to diverse operational contexts across multiple assignments, demonstrating reliability in a multilingual Swiss work environment"
      ]
    },
    {
      "period": "03.2023 -- 11.2024",
      "title": "NetSuite Developer & Business Process Analyst (Internship)",
      "company": "Gestora de Inteligencia de Credito S.A. (QUOD) -- Sao Paulo, Brazil",
      "bullets": [
        "Developed SuiteScripts and automated workflows in Oracle NetSuite ERP using JavaScript and Node.js, reducing manual work by 40% and improving cross-departmental process efficiency",
        "Led testing and QA for NetSuite implementations; acted as liaison between IT, finance, and operations teams, translating business requirements into technical specifications and driving stakeholder alignment"
      ]
    },
    {
      "period": "05.2023 -- 01.2024",
      "title": "IT Resident (Technology Training Program)",
      "company": "BRISA / CIEDS -- Rio de Janeiro, Brazil",
      "bullets": [
        "Co-developed a full-stack event management platform including data modeling, backend logic, and workflow structure design",
        "Delivered 65% of project scope within program timeline; remaining 35% transitioned to partner company due to delayed requirements"
      ]
    },
    {
      "period": "04.2021 -- 01.2023",
      "title": "Administrative Support Intern",
      "company": "Criminal Registry -- High Court of the State of Rio de Janeiro, Brazil",
      "bullets": [
        "Contributed to digitization of criminal case archive: team virtualized 90% of physical records (2,000+ cases)",
        "Managed digital workflow of virtualized cases within the court's electronic case management system"
      ]
    }
  ],
  "education": [
    {
      "period": "03.2025 -- Present",
      "degree": "Postgraduate Studies in Data Science (expected 10.2026)",
      "institution": "UNIAMERICA University -- Remote"
    },
    {
      "period": "04.2022 -- 12.2024",
      "degree": "Bachelor's Degree in System Analysis and Development",
      "institution": "UNIAMERICA University -- Rio de Janeiro, Brazil"
    },
    {
      "period": "05.2023 -- 01.2024",
      "degree": "IT Residency Program (Software Development Focus)",
      "institution": "BRISA / CIEDS -- Rio de Janeiro, Brazil"
    }
  ],
  "hobbies": "Choral singing | Latin dance | Fitness & gym | Community volunteering"
}
""")

# Photo instructions
wf(f"{REPO}/config/PHOTO_INSTRUCTIONS.txt",
   "Place your professional photo here as 'photo.jpg' (portrait, ~400x500px).\n"
   "The CV will include it automatically. If no photo is found, CV generates without it.\n")

# 2. Create doc_generator.py
doc_generator_content = r'''import os, sys, json, re, textwrap, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utils import load_json, save_json, ensure_dir, now_iso
from kimi_client import KimiClient

KIMI_TIMEOUT = 30

def _generate_summary(client, profile, title, company, description):
    prompt = (
        f"Candidate: {profile['name']} -- {profile['role']}.\n"
        f"Experience highlights:\n"
        + "\n".join(f"- {exp['title']} @ {exp['company']}" for exp in profile["experience"])
        + f"\n\nSkills: {', '.join(profile['skills']['technical_default'])}\n\n"
        f"Job: {title} at {company}.\nDescription: {description}\n\n"
        "Write a concise professional Profile Summary (3-4 sentences, max 60 words) connecting the candidate's key strengths to THIS specific job. Return ONLY the summary text."
    )
    r = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=200,
        response_format={"type": "text"},
    )
    if r is None:
        return ("Data Analyst with proven experience in data visualization, process automation, and cross-functional communication. "
                "Skilled in Python, JavaScript, Power BI, and NetSuite, with a track record of reducing manual work by 40% and increasing engagement by 35%. "
                "Committed to turning data into actionable insights and building systems that improve team efficiency.")
    return r.strip()

def _generate_cover_letter(client, profile, title, company, location, description, score):
    job_desc = textwrap.shorten(description, width=600, placeholder="...")
    prompt = (
        f"Candidate: {profile['name']} ({profile['role']})\n"
        f"Address: {profile['address']}\n"
        f"LinkedIn: {profile['linkedin']}\n\n"
        "Experience:\n"
        + "\n".join(f"- {e['title']} @ {e['company']}" for e in profile["experience"])
        + f"\n\nSkills: {', '.join(profile['skills']['technical_default'])}\n"
        f"Languages: EN (professional), PT (native), DE (A2, learning)\n\n"
        f"Job to apply: {title} at {company} ({location or 'Switzerland'})\n"
        f"Description: {job_desc}\n"
        f"Evaluation score: {score}/100\n\n"
        "Write a 4-paragraph formal cover letter.\n"
        "1. State enthusiasm and explain why this specific role fits the candidate's path.\n"
        "2. Mention 2-3 relevant experiences with brief concrete results (use metrics from experience bullets).\n"
        "3. Emphasise cross-cultural adaptability (moved to Switzerland April 2025, speaks EN/PT, learning DE).\n"
        "4. Request an interview, mention the portfolio/project pipeline project.\n"
        "Do NOT include addresses, dates, or signatures in the body.\n"
        "Return ONLY the 4-paragraph text in English."
    )
    r = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=800,
        response_format={"type": "text"},
    )
    if r is None:
        r = (
            f"Dear Hiring Manager,\n\n"
            f"I am excited to apply for the {title} role at {company}. "
            f"Having recently relocated to Switzerland in April 2025, I am actively building my career in the Swiss market, and this position aligns perfectly with my background in data analysis, business process optimisation, and cross-functional collaboration.\n\n"
            f"During my internship at Gestora de Inteligencia de Credito S.A., I developed SuiteScripts and automated workflows in Oracle NetSuite, reducing manual work by 40% and improving efficiency across finance and operations teams. "
            f"At netzdenker.com, I used Python and AI tools to overhaul the company website, increasing page views and clicks by 35%. "
            f"These experiences have sharpened my ability to translate business needs into technical solutions and deliver measurable results.\n\n"
            f"Beyond my technical skills in Python, JavaScript, Power BI, and NetSuite, I bring a strong international mindset. "
            f"I am fluent in English and Portuguese, and I am actively learning German (A2 level), which reflects my commitment to integrating fully into the Swiss professional environment.\n\n"
            f"I would welcome the opportunity to discuss how my experience and skills can contribute to your team. "
            f"You can also explore my portfolio and project work on GitHub. Thank you for considering my application.\n\n"
            f"Kind regards,\n{profile['name']}"
        )
    return r.strip()

def _role_keywords(title):
    title_lower = title.lower()
    if any(k in title_lower for k in ["data", "analyst", "business intelligence", "bi"]):
        return "data_focused"
    if any(k in title_lower for k in ["ai", "ml", "machine learning", "nlp"]):
        return "ai_focused"
    return "default"
'''
wf(f"{REPO}/agents/doc_generator.py", doc_generator_content)

# Continue doc_generator.py part 2
doc_generator_part2 = r'''
# Import FPDF2
try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except Exception:
    FPDF_AVAILABLE = False
    print("WARNING: fpdf2 not available; PDF generation disabled. Install: pip install fpdf2>=2.8.0")

def _safe_text(text):
    """Remove emojis and non-Latin-1 chars for PDF compatibility."""
    if not text:
        return ""
    text = text.encode("latin-1", "ignore").decode("latin-1")
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return text

def cv_pdf(profile, job, summary, path):
    if not FPDF_AVAILABLE:
        raise RuntimeError("fpdf2 is not installed")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    m = 10
    pdf.set_margins(m, m, m)
    w = 210 - 2*m

    # Header
    if os.path.exists(profile.get("photo_path", "")):
        try:
            pdf.image(profile["photo_path"], x=170, y=10, w=30)
        except Exception:
            pass

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, _safe_text(profile["name"]), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _safe_text(f"{profile['role']} | {profile['location']}"), ln=True)
    pdf.cell(0, 5, _safe_text(f"{profile['phone']} | {profile['email']} | {profile['linkedin']}"), ln=True)
    pdf.cell(0, 5, _safe_text(f"Permit: {profile['permit']} | Notice: {profile['notice_period']}"), ln=True)
    pdf.ln(3)

    # AI-tailored summary
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "PROFILE SUMMARY", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(w, 5, _safe_text(summary))
    pdf.ln(2)

    # Skills
    role_key = _role_keywords(job.get("titulo", ""))
    skill_key = f"technical_{role_key}" if f"technical_{role_key}" in profile["skills"] else "technical_default"
    tech_skills = profile["skills"].get(skill_key, profile["skills"]["technical_default"])
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "SKILLS", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(w, 5, _safe_text(
        "Technical: " + ", ".join(tech_skills) +
        " | Communication: " + ", ".join(profile["skills"]["communication"]) +
        " | Certifications: " + ", ".join(profile["skills"]["certifications"])
    ))
    pdf.ln(2)

    # Experience
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "EXPERIENCE", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for exp in profile["experience"]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, _safe_text(f"{exp['title']} -- {exp['company']} | {exp['period']}"), ln=True)
        pdf.set_font("Helvetica", "", 10)
        for b in exp["bullets"]:
            pdf.multi_cell(w, 4, _safe_text("  -- " + b))
        pdf.ln(1)
    pdf.ln(1)

    # Education
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "EDUCATION", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for edu in profile["education"]:
        pdf.cell(0, 5, _safe_text(f"{edu['degree']} | {edu['institution']} | {edu['period']}"), ln=True)
    pdf.ln(2)

    # Languages
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "LANGUAGES", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, "English (Professional) | Portuguese (Native) | German (A2, learning)", ln=True)
    pdf.ln(2)

    # Hobbies
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "HOBBIES & INTERESTS", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(w, 5, _safe_text(profile["hobbies"]))

    pdf.output(path)
'''
wf(f"{REPO}/agents/doc_generator.py", doc_generator_part2)

# Continue doc_generator.py part 3
doc_generator_part3 = r'''
def cl_pdf(profile, letter, title, company, location, path):
    if not FPDF_AVAILABLE:
        raise RuntimeError("fpdf2 is not installed")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    m = 15
    pdf.set_margins(m, m, m)
    w = 210 - 2*m

    # Date + addresses
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, now_iso().split("T")[0], ln=True)
    pdf.ln(4)
    pdf.multi_cell(w, 5, _safe_text(f"{profile['name']}\n{profile['address']}\n{profile['phone']}\n{profile['email']}\n{profile['linkedin']}"))
    pdf.ln(3)
    pdf.multi_cell(w, 5, _safe_text(f"{company}\n{location or 'Switzerland'}"))
    pdf.ln(5)

    # Subject
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _safe_text(f"Re: Application for {title}"), ln=True)
    pdf.ln(3)

    # Body
    pdf.set_font("Helvetica", "", 11)
    for para in letter.split("\n\n"):
        para = para.strip()
        if para:
            pdf.multi_cell(w, 6, _safe_text(para))
            pdf.ln(2)

    # Signature
    pdf.ln(4)
    pdf.cell(0, 6, _safe_text(f"Kind regards,"), ln=True)
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _safe_text(profile["name"]), ln=True)

    pdf.output(path)

def main():
    evals = load_json("job_evaluations_latest.json")
    profile = load_json("config/candidate_profile.json")
    client = KimiClient()
    gen_dir = "generated_docs"
    ensure_dir(gen_dir)

    if not evals:
        print("No evaluations found."); return

    for ev in evals:
        score = ev.get("score", 0)
        if score < 45:
            continue
        job = ev.get("job", ev)
        title = job.get("titulo", job.get("title", "Job"))
        company = job.get("empresa", job.get("company", "Company"))
        location = job.get("localizacao", job.get("location", ""))
        desc = job.get("descricao", job.get("description", ""))

        safe_name = re.sub(r"[^\w\-]", "_", f"{company}_{title}")[:60]
        folder = os.path.join(gen_dir, safe_name)
        ensure_dir(folder)

        print(f"[doc_generator] Generating for {title} @ {company} (score {score})")

        summary = _generate_summary(client, profile, title, company, desc)
        letter = _generate_cover_letter(client, profile, title, company, location, desc, score)
        time.sleep(1.5)

        if FPDF_AVAILABLE:
            cv_pdf(profile, job, summary, os.path.join(folder, f"CV_{safe_name}.pdf"))
            cl_pdf(profile, letter, title, company, location, os.path.join(folder, f"CL_{safe_name}.pdf"))
            save_json(os.path.join(folder, "ai_summary.json"), {"summary": summary, "letter": letter, "score": score})
            print(f"  Saved to {folder}/")
        else:
            save_json(os.path.join(folder, "ai_summary.json"), {"summary": summary, "letter": letter, "score": score})
            print(f"  Saved JSON only (fpdf2 missing): {folder}/")

if __name__ == "__main__":
    main()
'''
wf(f"{REPO}/agents/doc_generator.py", doc_generator_part3)

# 3. Add python-docx and fpdf2 to requirements.txt
req_path = f"{REPO}/requirements.txt"
reqs = open(req_path, "r").read() if os.path.exists(req_path) else ""
for dep in ["python-docx>=1.1.0", "fpdf2>=2.8.0"]:
    if dep not in reqs:
        with open(req_path, "a") as f:
            f.write(dep + "\n")
        print(f"  Added {dep} to requirements.txt")

# 4. Update workflow to run doc_generator.py
ci_path = f"{REPO}/.github/workflows/job-hunt-scheduler.yml"
ci = open(ci_path, "r").read()
if "doc_generator.py" not in ci:
    ci = ci.replace(
        "run: python agents/high_score_alert.py",
        "run: python agents/doc_generator.py\n        continue-on-error: true\n\n      - name: High-Score Alerts\n        run: python agents/high_score_alert.py"
    )
    with open(ci_path, "w") as f:
        f.write(ci)
    print("  Updated .github/workflows/job-hunt-scheduler.yml")

# 5. Verify files exist
for f in ["agents/doc_generator.py", "config/candidate_profile.json"]:
    fp = f"{REPO}/{f}"
    if os.path.exists(fp):
        sz = os.path.getsize(fp)
        print(f"  {f}: {sz} bytes")
    else:
        print(f"  MISSING: {f}")

# 6. Git commit
os.chdir(REPO)
rc, out, err = run("git add -A")
rc2, out2, err2 = run('git commit -m "feat: tailored CV+CL v2 (Phase 8v2)"')
if rc2:
    print(f"\nCommitted: {out2.strip()}")
else:
    print(f"\nCommit issue (maybe nothing to commit): {err2.strip()}")

print("\n=== PHASE 8v2 DONE ===")
print("Next steps:")
print("  1. Add your photo as config/photo.jpg (~400x500px portrait)")
print("  2. Install deps locally: pip install -r requirements.txt")
print("  3. Test: python agents/doc_generator.py")
print("  4. Rebase & push: git pull --rebase origin main && git push origin main")
