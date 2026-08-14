"""
form_fill_guide.py  —  Generates guides for Claude in Chrome to fill out forms
Analyzes the job and creates optimized instructions
"""

import json
import os
from datetime import datetime


# Personal data loaded from config/candidate_profile.json (not in git)
# -- never hardcode PII here, this file goes to a public repo
def _load_personal_data() -> dict:
    try:
        with open("config/candidate_profile.json", encoding="utf-8") as f:
            p = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        p = {}
    return {
        "full_name": p.get("name", ""),
        "email": p.get("email", ""),
        "phone": p.get("phone", ""),
        "location": p.get("location", ""),
        "linkedin": p.get("linkedin", ""),
        "github": p.get("github", ""),
        "website": "",
        "cv_path": "Carlos_Baptista_CV_Master_v3.docx",
        "work_permit": p.get("permit", ""),
        "nationality": p.get("nationality", ""),
        "languages": {
            "portuguese": "Native",
            "english": "C1 Advanced",
            "spanish": "B2 Intermediate",
            "german": "A2 (improving)",
        },
        "availability": f"On {p.get('notice_period', '2 weeks')}' notice",
    }


CARLOS_DATA = _load_personal_data()

# Mapping of common ATS fields
_name_parts = CARLOS_DATA["full_name"].split()
COMMON_FIELDS = {
    "first_name": _name_parts[0] if _name_parts else "",
    "last_name": _name_parts[-1] if _name_parts else "",
    "email": CARLOS_DATA["email"],
    "phone": CARLOS_DATA["phone"],
    "location": CARLOS_DATA["location"],
    "country": "Switzerland",
    "linkedin_url": CARLOS_DATA["linkedin"],
    "work_experience": "Business Process Analyst at QUOD (Brazil) & Digital Marketing Analyst at netzdenker.com",
    "education": "Postgraduate in Data Science (expected Oct 2026), Bachelor in Systems Analysis",
    "skills": "Power BI, GA4, Data Analysis, Business Analysis, AI Tools (Claude, ChatGPT)",
    "certifications": "Google AI Essentials, Anthropic Claude Courses, GA4 Certification",
    "cover_letter": "",  # Will be filled from the approval
    "resume": CARLOS_DATA["cv_path"],
}


def generate_form_fill_guide(job_eval: dict, approval: dict) -> dict:
    """
    Generates a structured guide for Claude in Chrome to fill out the form.
    Returns optimized step-by-step instructions.
    """
    job = approval.get("job", {})
    empresa = job.get("empresa", "")
    titulo = job.get("titulo", "")
    url = job.get("url", "")

    guide = {
        "generated_at": datetime.now().isoformat(),
        "empresa": empresa,
        "titulo": titulo,
        "url": url,
        "score": approval.get("score", 0),
        "instructions": [],
        "form_fields": {},
        "data_to_fill": COMMON_FIELDS.copy(),
    }

    # Generic instructions (work for most ATS)
    guide["instructions"] = [
        f"1. Open this link in the browser: {url}",
        "2. Wait for the page to fully load",
        "3. If there is an 'Apply' button, click it",
        "4. Fill in the required fields with the data below",
        "5. For file fields (CV/Resume), upload: CV_Master.docx",
        "6. Review all information",
        "7. Click 'Submit' or 'Send Application'",
    ]

    # Expected common fields
    guide["form_fields"] = {
        "personal_info": {
            "first_name": "Carlos",
            "last_name": "Baptista",
            "email": CARLOS_DATA["email"],
            "phone": CARLOS_DATA["phone"],
            "location": CARLOS_DATA["location"],
            "country": "Switzerland",
        },
        "professional_info": {
            "linkedin_url": CARLOS_DATA["linkedin"],
            "years_experience": "2+ years (QUOD + netzdenker.com)",
            "current_role": "Digital Marketing & Analytics Associate",
            "skills": "Power BI, GA4, Data Analysis, Business Analysis, AI Tools",
        },
        "education": {
            "degree": "Bachelor in Systems Analysis and Development",
            "university": "UNIAMERICA University",
            "field": "Systems Analysis / Data Science",
            "graduation_year": "2024",
            "additional": "Postgraduate in Data Science (expected Oct 2026)",
        },
        "files": {
            "resume_file": "Carlos_Baptista_CV_Master_v3.docx",
            "cover_letter": "Use the cover letter provided if available",
        },
    }

    # Hints by ATS type (automatic detection)
    ats_hints = {
        "workday": [
            "Workday is formal and structured",
            "Fill in 'First Name' and 'Last Name' separately",
            "Look for 'Phone Number (Country Code)' format",
            "Usually asks for LinkedIn URL",
        ],
        "greenhouse": [
            "Greenhouse is clean and modern",
            "Fields appear progressively",
            "If asked 'Authorized to work in Switzerland', answer YES",
            "Resume is required",
        ],
        "lever": [
            "Lever is intuitive and mobile-friendly",
            "Look for the 'How did you hear about us?' dropdown",
            "If there is a 'Portfolio' or 'Website' field, leave it blank if you don't have one",
        ],
        "generic": [
            "If the form is not recognized, fill in the basic fields",
            "Prioritize: email, phone, location, resume",
            "For optional fields, leave blank if you don't have the data",
        ],
    }

    guide["ats_hints"] = ats_hints

    return guide


def save_form_guides(approvals: list, evals_dict: dict) -> list:
    """Saves guides for all approved applications."""
    guides = []
    os.makedirs("digests", exist_ok=True)

    for approval in approvals:
        empresa = approval.get("empresa", "")
        eval_data = evals_dict.get(empresa, {})

        guide = generate_form_fill_guide(eval_data, approval)
        guides.append(guide)

        # Save individual guide
        filename = f"digests/form_guide_{empresa.replace(' ', '_')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(guide, f, ensure_ascii=False, indent=2)

    # Save all guides to a single file
    if guides:
        all_guides_file = "digests/form_guides_latest.json"
        with open(all_guides_file, "w", encoding="utf-8") as f:
            json.dump(guides, f, ensure_ascii=False, indent=2)

    return guides


def generate_claude_in_chrome_prompt(guide: dict) -> str:
    """
    Generates an optimized prompt to paste directly into Claude in Chrome.
    """
    empresa = guide["empresa"]
    titulo = guide["titulo"]
    url = guide["url"]
    data = guide["data_to_fill"]
    form_fields = guide["form_fields"]

    prompt = f"""
You are a form-filling assistant. Your task is to fill out a job application form.

JOB DETAILS:
- Company: {empresa}
- Position: {titulo}
- URL: {url}

INSTRUCTIONS:
1. Open the URL above
2. Fill in the form with the data provided below
3. For file uploads, use the CV file when prompted
4. Review all information carefully
5. Click Submit/Send when complete
6. Take a screenshot of the confirmation

DATA TO FILL:
- Full Name: {data.get('full_name', '')}
- Email: {data.get('email', '')}
- Phone: {data.get('phone', '')}
- Location: {data.get('location', '')}
- LinkedIn: {data.get('linkedin', '')}
- Work Experience: Business Process Analyst at QUOD (Brazil) + Digital Marketing Analyst at netzdenker.com
- Skills: Power BI, GA4, Data Analysis, Business Analysis, AI tools (Claude, ChatGPT, Gemini)
- Certifications: Google AI Essentials (2025), Anthropic Claude Courses (2026), GA4 Certification (2026)
- Education: Bachelor in Systems Analysis (2024), Postgraduate in Data Science (expected Oct 2026)
- Work Permit: Swiss Work Permit B (valid)
- Availability: On 2 weeks' notice

FORM FIELDS TO FILL:
{json.dumps(form_fields, ensure_ascii=False, indent=2)}

After completing the form, confirm that all information is correct and take a final screenshot.
"""

    return prompt


if __name__ == "__main__":
    import sys

    # Test: generate a sample guide
    sample_approval = {
        "empresa": "Test Company",
        "titulo": "Data Analyst Internship",
        "url": "https://example.com/jobs/123",
        "score": 85,
    }

    sample_eval = {
        "score": 85,
        "recommendation": "APPLY",
    }

    guide = generate_form_fill_guide(sample_eval, sample_approval)

    print("[OK] Form Fill Guide Generated:")
    print(json.dumps(guide, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print("PROMPT FOR CLAUDE IN CHROME:")
    print("=" * 70)
    print(generate_claude_in_chrome_prompt(guide))
