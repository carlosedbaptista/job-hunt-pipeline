import os, sys, json, re, textwrap, time, html
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utils import load_json, save_json, ensure_dir, now_iso, effective_decision
from kimi_client import KimiClient
from gdrive_uploader import upload_cv_cl, GDRIVE_AVAILABLE as GDRIVE_UPLOADER_AVAILABLE
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from email_notifier import send_email

KIMI_TIMEOUT = 30

def _generate_summary(client, profile, title, company, description):
    prompt = (
        f"Candidate: {profile['name']} -- {profile.get('role', '')}.\n"
        + (f"Seeking: {profile['target_role']}\n" if profile.get("target_role") else "")
        + f"Experience highlights:\n"
        + "\n".join(f"- {exp.get('title', '')} @ {exp.get('company', '')}"
                    for exp in profile.get("experience", []))
        + f"\n\nSkills: {', '.join(profile.get('skills', {}).get('technical_default', []))}\n\n"
        f"Job: {title} at {company}.\nDescription: {description}\n\n"
        "Write a concise professional Profile Summary (3-4 sentences, max 60 words) "
        "connecting the candidate's key strengths to THIS specific job. Use only facts "
        "given above; invent nothing. Return ONLY the summary text."
    )
    r = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=200,
        response_format={"type": "text"},
    )
    if r is None:
        # Fallback derived from the profile: the old literal described a
        # "Data Analyst ... JavaScript, Power BI, NetSuite", which stopped
        # being true when the positioning changed, and it goes into a PDF
        # sent to employers.
        return (profile.get("summary")
                or f"{profile.get('role', '')}. "
                   f"Skills: {', '.join(profile.get('skills', {}).get('technical_default', [])[:8])}.")
    return r.strip()

def _load_text_model(path: str) -> str:
    """Reads an optional plain-text style model (config/cv_model.txt,
    config/cover_letter_model.txt). These are restored in CI from the
    CV_MODEL_B64 / CL_MODEL_B64 secrets and were, until now, never read by
    any code path."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _generate_cover_letter(client, profile, title, company, location, description, score):
    job_desc = textwrap.shorten(description, width=600, placeholder="...")

    # Every fact below comes from the profile. Nothing about the candidate is
    # hardcoded here: the languages line used to read "DE (A2, learning)" as
    # a literal, so the moment he reaches B1 the CV would say B1 while every
    # cover letter for the same job still said A2 -- and this is text sent to
    # employers. Same reason the relocation sentence is now conditional.
    languages = profile.get("languages", "")
    target = profile.get("target_role", "")
    summary = profile.get("summary", "")
    projects = profile.get("projects", [])
    project_line = "; ".join(pr.get("title", "") for pr in projects[:2])
    relocation = profile.get("relocation_date", "")

    # Optional voice reference: config/cover_letter_model.txt, restored in CI
    # from the CL_MODEL_B64 secret. It was being restored and then ignored by
    # every code path -- now it steers the tone.
    model_letter = _load_text_model("config/cover_letter_model.txt")

    prompt = (
        f"Candidate: {profile['name']} ({profile.get('role', '')})\n"
        f"Address: {profile.get('address', '')}\n"
        f"LinkedIn: {profile.get('linkedin', '')}\n"
        + (f"Seeking: {target}\n" if target else "")
        + (f"In his own words: {summary}\n" if summary else "")
        + "\nExperience:\n"
        + "\n".join(f"- {e.get('title', '')} @ {e.get('company', '')}"
                    for e in profile.get("experience", []))
        + f"\n\nSkills: {', '.join(profile.get('skills', {}).get('technical_default', []))}\n"
        + (f"Projects: {project_line}\n" if project_line else "")
        + (f"Languages: {languages}\n" if languages else "")
        + (f"Relocated to Switzerland: {relocation}\n" if relocation else "")
        + f"\nJob to apply: {title} at {company} ({location or 'Switzerland'})\n"
        f"Description: {job_desc}\n"
        f"Evaluation score: {score}/100\n\n"
        "Write a 4-paragraph formal cover letter in English.\n"
        "1. State genuine interest and explain why THIS specific role fits where he is "
        "heading, using the 'Seeking' line above rather than his current job title.\n"
        "2. Two or three relevant experiences with concrete results, taking the metrics "
        "from the experience bullets. Prefer specifics over adjectives.\n"
        "3. What he brings beyond the checklist: career changer who moves fast into "
        "unfamiliar domains, ships to production, and audits his own work. Mention the "
        "language situation only if the posting raises it, and state it exactly as the "
        "Languages line above says -- never upgrade it.\n"
        "4. Request an interview and reference the portfolio project by name.\n"
        "Rules: no invented facts, employers, dates, metrics or technologies -- use ONLY "
        "what is above. No addresses, dates or signatures in the body. No em dashes. "
        "Return ONLY the four paragraphs."
    )
    if model_letter:
        prompt += (
            "\n\nReference letter previously written by the candidate. Match its voice, "
            "rhythm and level of concreteness. Do NOT copy its sentences or reuse its "
            "company-specific details:\n---\n"
            + textwrap.shorten(model_letter, width=2500, placeholder="...")
            + "\n---"
        )
    r = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=800,
        response_format={"type": "text"},
    )
    if r is None:
        # Offline fallback, used when the LLM call fails. It used to be a
        # fully written letter with facts baked in ("relocated in April
        # 2025", "German (A2 level)", "JavaScript, Power BI") that drifted
        # out of date the moment the CV changed -- and this text goes to
        # employers. It now says only what the profile says, and says less.
        top_experience = (profile.get("experience") or [{}])[0]
        r = (
            f"Dear Hiring Manager,\n\n"
            f"I am writing to apply for the {title} role at {company}. "
            + (f"I am currently {top_experience.get('title', '')} at "
               f"{str(top_experience.get('company', '')).split('--')[0].strip()}, "
               if top_experience.get("title") else "")
            + (f"and I am looking for {profile.get('target_role', '')}. "
               if profile.get("target_role") else "")
            + "\n\n"
            + (f"{profile.get('summary', '')}\n\n" if profile.get("summary") else "")
            + (f"Languages: {profile.get('languages', '')}.\n\n"
               if profile.get("languages") else "")
            + "I would welcome the opportunity to discuss how I could contribute to "
            "your team, and you can find my project work on GitHub. Thank you for "
            f"considering my application.\n\nKind regards,\n{profile.get('name', '')}"
        )
    return r.strip()

def _role_keywords(title):
    title_lower = title.lower()
    if any(k in title_lower for k in ["data", "analyst", "business intelligence", "bi"]):
        return "data_focused"
    if any(k in title_lower for k in ["ai", "ml", "machine learning", "nlp"]):
        return "ai_focused"
    return "default"

# Import FPDF2
try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
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
    # Was auto=False: anything past the bottom of page 1 was silently dropped,
    # and this profile has four roles with bullets. A CV that loses its last
    # section without telling anyone is worse than a two-page CV.
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    m = 10
    pdf.set_margins(m, m, m)
    w = 210 - 2*m

    # Header with photo. The image occupies x=165..200, so the header text is
    # given a reduced width instead of the full page: it used to run under the
    # photo, and the profile summary started before the image ended.
    photo_w = 0
    if os.path.exists(profile.get("photo_path", "")):
        try:
            pdf.image(profile["photo_path"], x=165, y=10, w=35)
            photo_w = 40
        except Exception:
            photo_w = 0
    header_w = w - photo_w

    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(header_w, 8, _safe_text(profile["name"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    for line in (f"{profile.get('role', '')} | {profile.get('location', '')}",
                 f"{profile.get('phone', '')} | {profile.get('email', '')} | {profile.get('linkedin', '')}",
                 f"Permit: {profile.get('permit', '')} | Notice: {profile.get('notice_period', '')}"):
        pdf.multi_cell(header_w, 5, _safe_text(line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # Clear the photo before the first full-width block.
    if photo_w:
        pdf.set_y(max(pdf.get_y(), 10 + 35 * 5 / 4 + 3))
    pdf.ln(3)

    # AI-tailored summary
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "PROFILE SUMMARY", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(w, 5, _safe_text(summary), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # Skills
    role_key = _role_keywords(job.get("title", ""))
    skill_key = f"technical_{role_key}" if f"technical_{role_key}" in profile["skills"] else "technical_default"
    tech_skills = profile["skills"].get(skill_key, profile["skills"]["technical_default"])
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "SKILLS", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(w, 5, _safe_text(
        "Technical: " + ", ".join(tech_skills) +
        " | Communication: " + ", ".join(profile["skills"].get("communication", [])) +
        " | Certifications: " + ", ".join(profile["skills"].get("certifications", []))
    ), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # Experience
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "EXPERIENCE", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for exp in profile["experience"]:
        pdf.set_font("Helvetica", "B", 10)
        # multi_cell, not cell: cell() clips at the right margin, and these
        # lines are long ("Business Process & NetSuite Intern -- Gestora de
        # Inteligencia de Credito S.A. -- credit-intelligence bureau | ...").
        pdf.multi_cell(w, 5, _safe_text(f"{exp['title']} -- {exp['company']} | {exp['period']}"),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 10)
        for b in exp["bullets"]:
            pdf.multi_cell(w, 4, _safe_text("  -- " + b), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
    pdf.ln(1)

    # Education
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "EDUCATION", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for edu in profile["education"]:
        pdf.multi_cell(w, 5, _safe_text(f"{edu['degree']} | {edu['institution']} | {edu['period']}"),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # Languages
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "LANGUAGES", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _safe_text(profile.get("languages", "")), ln=True)
    pdf.ln(2)

    # Hobbies -- omitted entirely when empty, rather than leaving a dangling
    # heading with nothing under it on a CV sent to an employer.
    if str(profile.get("hobbies", "")).strip():
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "HOBBIES & INTERESTS", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(w, 5, _safe_text(profile["hobbies"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(path)

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
    pdf.multi_cell(w, 5, _safe_text(f"{profile['name']}\n{profile['address']}\n{profile['phone']}\n{profile['email']}\n{profile['linkedin']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.multi_cell(w, 5, _safe_text(f"{company}\n{location or 'Switzerland'}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
            pdf.multi_cell(w, 6, _safe_text(para), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)

    # Signature
    pdf.ln(4)
    pdf.cell(0, 6, _safe_text("Kind regards,"), ln=True)
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _safe_text(profile["name"]), ln=True)

    pdf.output(path)

def _email_docs_to_candidate(folder, title, company, score, paths):
    """Mails the generated CV/CL to the candidate.

    Why this exists: the repo is public, so the PDFs can be neither committed
    nor uploaded as an Actions artifact (they carry full name, phone, personal
    e-mail, LinkedIn, permit status and photo), and the Google Drive upload
    fails with "Service Accounts do not have storage quota" until
    GDRIVE_REFRESH_TOKEN_B64 is set. Without this the documents live only on
    the runner and die with it. Recipient is always GMAIL_RECIPIENT -- the
    candidate -- never a recruiter.
    """
    sender = os.environ.get("GMAIL_SENDER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("GMAIL_RECIPIENT")
    if not (sender and password and recipient):
        print("  [mail] GMAIL_* not configured -- CV/CL not mailed (they live only on this machine)")
        return False

    body = (
        f"<p>Tailored application materials for <b>{html.escape(str(title))}</b> "
        f"at <b>{html.escape(str(company))}</b> (match {html.escape(str(score))}).</p>"
        "<p>Attached: CV and cover letter. Review them before sending anything: "
        "nothing has been submitted to the employer.</p>"
    )
    # The subject is a mail HEADER, and title/company are scraped from
    # third-party job alerts: a newline in either would inject headers.
    # Collapse whitespace and cap the length.
    subject = " ".join(f"[Job Hunt] CV + cover letter: {title} @ {company}".split())[:180]
    ok = send_email(recipient, subject, body, sender, password, attachments=paths)
    print(f"  [mail] {'Sent to candidate' if ok else 'Send FAILED'}: {len(paths)} file(s)")
    return ok


def generate_docs_for_job(client, profile, ev: dict, gen_dir: str = "generated_docs") -> str | None:
    """Generates (and, if configured, uploads to Drive) the CV/CL for a
    single evaluation record. Shared by main() (daily batch, reads
    job_evaluations_latest.json) and agents/add_job.py (single manual
    evaluation) -- the two used to be on separate tracks entirely, so a
    manually-added job scoring APPLY never got tailored materials no
    matter how high it scored. Returns the output folder, or None on
    failure/skip."""
    score = ev.get("score") or 0  # ERROR evaluations carry score None
    # Only APPLY jobs get tailored materials -- the EFFECTIVE decision:
    # a hard-blocked or low-confidence (insufficient_info) job keeps its
    # high score visible but must never trigger automatic CV/CL generation.
    if effective_decision(ev) != "APPLY":
        return None

    job = ev.get("job", ev)
    title = job.get("title", "Job")
    company = job.get("company", "Company")
    location = job.get("location", "")
    desc = job.get("description", "")

    safe_name = re.sub(r"[^\w\-]", "_", f"{company}_{title}")[:60]
    folder = os.path.join(gen_dir, safe_name)
    ensure_dir(folder)

    print(f"[doc_generator] Generating for {title} @ {company} (score {score})")

    try:
        summary = _generate_summary(client, profile, title, company, desc)
        letter = _generate_cover_letter(client, profile, title, company, location, desc, score)
    except Exception as e:
        print(f"  [doc_generator] API error for {company} -- skipping ({type(e).__name__}: {str(e)[:120]})")
        return None
    time.sleep(1.5)

    if FPDF_AVAILABLE:
        cv_pdf(profile, job, summary, os.path.join(folder, f"CV_{safe_name}.pdf"))
        cl_pdf(profile, letter, title, company, location, os.path.join(folder, f"CL_{safe_name}.pdf"))
        save_json(os.path.join(folder, "ai_summary.json"), {"summary": summary, "letter": letter, "score": score})
        print(f"  Saved to {folder}/")

        # Upload to Google Drive
        if GDRIVE_UPLOADER_AVAILABLE:
            try:
                upload_cv_cl(folder, company, title)
            except Exception as e:
                print(f"  [GDrive] Upload failed (continuing): {e}")

        # Mail the PDFs to the candidate. Independent of Drive on purpose:
        # Drive is the one that has been silently failing, and a generated
        # document that reaches nobody is the same as no document.
        try:
            _email_docs_to_candidate(
                folder, title, company, score,
                [os.path.join(folder, f"CV_{safe_name}.pdf"),
                 os.path.join(folder, f"CL_{safe_name}.pdf")],
            )
        except Exception as e:
            print(f"  [mail] Failed (continuing): {type(e).__name__}: {str(e)[:120]}")
    else:
        save_json(os.path.join(folder, "ai_summary.json"), {"summary": summary, "letter": letter, "score": score})
        print(f"  Saved JSON only (fpdf2 missing): {folder}/")

    return folder


def main():
    evals = load_json("digests/job_evaluations_latest.json")
    profile = load_json("config/candidate_profile.json")
    client = KimiClient()
    gen_dir = "generated_docs"
    ensure_dir(gen_dir)

    if not evals:
        print("No evaluations found."); return
    if not profile:
        print("config/candidate_profile.json missing or invalid (check CANDIDATE_PROFILE_B64 secret) -- skipping doc generation")
        return

    generated = 0
    for ev in evals:
        if generate_docs_for_job(client, profile, ev, gen_dir):
            generated += 1
    # Say so out loud. This step used to print absolutely nothing when no job
    # reached APPLY, which is indistinguishable from a crash in the CI log.
    print(f"[doc_generator] {generated} job(s) got tailored documents "
          f"out of {len(evals)} evaluated (only APPLY qualifies).")

if __name__ == "__main__":
    main()
