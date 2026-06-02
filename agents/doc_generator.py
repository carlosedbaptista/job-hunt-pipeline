
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
