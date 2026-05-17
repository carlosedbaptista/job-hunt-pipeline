"""
form_fill_guide.py  —  Gera guias pra Claude in Chrome preencher formulários
Analisa a vaga e cria instruções otimizadas
"""

import json
import os
from datetime import datetime


# Dados pessoais de Carlos (pré-preenchidos)
CARLOS_DATA = {
    "full_name": "Carlos Eduardo Duarte Baptista",
    "email": "carlosedbaptista@gmail.com",
    "phone": "+41 78 261 34 74",
    "location": "Wallisellen, Switzerland",
    "linkedin": "linkedin.com/in/carlosedbaptista",
    "github": "",  # Adicionar se tiver
    "website": "",  # Adicionar se tiver
    "cv_path": "Carlos_Baptista_CV_Master_v3.docx",
    "work_permit": "Swiss Work Permit B (valid)",
    "nationality": "Brazilian",
    "languages": {
        "portuguese": "Native",
        "english": "C1 Advanced",
        "spanish": "B2 Intermediate",
        "german": "A2 (improving)",
    },
    "availability": "On 2 weeks' notice",
}

# Mapeamento de campos comuns em ATS
COMMON_FIELDS = {
    "first_name": "Carlos",
    "last_name": "Baptista",
    "email": CARLOS_DATA["email"],
    "phone": CARLOS_DATA["phone"],
    "location": CARLOS_DATA["location"],
    "country": "Switzerland",
    "linkedin_url": CARLOS_DATA["linkedin"],
    "work_experience": "Business Process Analyst at QUOD (Brazil) & Digital Marketing Analyst at netzdenker.com",
    "education": "Postgraduate in Data Science (expected Oct 2026), Bachelor in Systems Analysis",
    "skills": "Power BI, GA4, Data Analysis, Business Analysis, AI Tools (Claude, ChatGPT)",
    "certifications": "Google AI Essentials, Anthropic Claude Courses, GA4 Certification",
    "cover_letter": "",  # Será preenchido da aprovação
    "resume": CARLOS_DATA["cv_path"],
}


def generate_form_fill_guide(job_eval: dict, approval: dict) -> dict:
    """
    Gera um guia estruturado pra Claude in Chrome preencher o formulário.
    Retorna instruções passo a passo otimizadas.
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

    # Instruções genéricas (funcionam pra maioria dos ATS)
    guide["instructions"] = [
        f"1. Abra este link no navegador: {url}",
        "2. Aguarde a página carregar completamente",
        "3. Se houver um botão 'Apply' ou 'Candidatar-se', clique",
        "4. Preencha os campos obrigatórios com os dados abaixo",
        "5. Para campos de arquivo (CV/Resume), faça upload de: CV_Master.docx",
        "6. Revise todas as informações",
        "7. Clique em 'Submit' ou 'Enviar Candidatura'",
    ]

    # Campos comuns esperados
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

    # Dicas por tipo de ATS (detecção automática)
    ats_hints = {
        "workday": [
            "Workday é formal e estruturado",
            "Preencha 'First Name' e 'Last Name' separadamente",
            "Procure por 'Phone Number (Country Code)' format",
            "Geralmente pede LinkedIn URL",
        ],
        "greenhouse": [
            "Greenhouse é cleanear e moderno",
            "Campos aparecem progressivamente",
            "Se pedir 'Authorized to work in Switzerland', marque SIM",
            "Resume é obrigatório",
        ],
        "lever": [
            "Lever é intuitivo e mobile-friendly",
            "Procure por dropdown de 'How did you hear about us?'",
            "Se houver campo de 'Portfolio' ou 'Website', deixe em branco se não tiver",
        ],
        "generic": [
            "Se o formulário não for reconhecido, preencha campos básicos",
            "Priorize: email, phone, location, resume",
            "Para campos opcionais, deixe em branco se não tiver dado",
        ],
    }

    guide["ats_hints"] = ats_hints

    return guide


def save_form_guides(approvals: list, evals_dict: dict) -> list:
    """Salva guias pra todas as aplicações aprovadas."""
    guides = []
    os.makedirs("digests", exist_ok=True)

    for approval in approvals:
        empresa = approval.get("empresa", "")
        eval_data = evals_dict.get(empresa, {})

        guide = generate_form_fill_guide(eval_data, approval)
        guides.append(guide)

        # Salva guia individual
        filename = f"digests/form_guide_{empresa.replace(' ', '_')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(guide, f, ensure_ascii=False, indent=2)

    # Salva todos os guias num arquivo
    if guides:
        all_guides_file = "digests/form_guides_latest.json"
        with open(all_guides_file, "w", encoding="utf-8") as f:
            json.dump(guides, f, ensure_ascii=False, indent=2)

    return guides


def generate_claude_in_chrome_prompt(guide: dict) -> str:
    """
    Gera um prompt otimizado pra colar direto no Claude in Chrome.
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

    # Teste: gera guia de exemplo
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

    print("✅ Form Fill Guide Generated:")
    print(json.dumps(guide, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print("PROMPT PRA CLAUDE IN CHROME:")
    print("=" * 70)
    print(generate_claude_in_chrome_prompt(guide))
