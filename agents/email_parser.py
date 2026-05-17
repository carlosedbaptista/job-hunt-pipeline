"""
email_parser.py  —  Subagente: extrai vagas de emails de alerta
Usa Claude Haiku (barato, rápido) para parsear o HTML de cada portal.
"""

import json
import os
import re
import anthropic

client = anthropic.Anthropic()  # usa ANTHROPIC_API_KEY do ambiente

# Mapeamento de remetente → nome do portal
PORTAL_MAP = {
    "jobs.ch": "jobs.ch",
    "jobup.ch": "jobup.ch",
    "linkedin.com": "linkedin",
    "jobalert@linkedin": "linkedin",
    "indeed.com": "indeed",
    "job-room.ch": "job-room",
    "avam.admin.ch": "job-room",
    "glassdoor.com": "glassdoor",
    "xing.com": "xing",
    "swissdevjobs.ch": "swissdevjobs",
}

SYSTEM_PROMPT = """You are a precise job listing extractor. Your only job is to extract job listings from email alert content.

Return ONLY a valid JSON array. No preamble, no explanation, no markdown code fences.

Each job in the array must have exactly these fields:
{
  "empresa": "Company name as written",
  "titulo": "Job title exactly as listed",
  "url": "Direct URL to job posting, or null",
  "descricao": "1-2 sentence summary of the role, or null",
  "localizacao": "City or region, or null",
  "idioma": "Language of the posting: en, de, fr, or mixed",
  "data_post": "Date posted YYYY-MM-DD format, or null",
  "portal": "Source portal identifier"
}

If zero job listings are found, return: []
Never add fields beyond those listed above."""


def detect_portal(email_from: str) -> str:
    """Detecta o portal pelo campo 'from' do email."""
    from_lower = email_from.lower()
    for pattern, portal in PORTAL_MAP.items():
        if pattern in from_lower:
            return portal
    return "unknown"


def clean_json_response(raw: str) -> str:
    """Remove markdown fences se o modelo as adicionar."""
    raw = raw.strip()
    # Remove ```json ... ``` ou ``` ... ```
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def parse_email(email: dict) -> list[dict]:
    """
    Usa Claude Haiku para extrair vagas de um único email.
    Retorna lista de vagas em formato padronizado.
    """
    portal = detect_portal(email["from"])

    # Prefere HTML (mais estruturado), fallback para texto
    body = email.get("html_body") or email.get("text_body") or ""

    # Trunca para caber no contexto do Haiku (evita custo desnecessário)
    MAX_BODY = 25_000
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n[conteúdo truncado]"

    if not body.strip():
        print(f"  ⚠️  Email {email['id']} sem corpo. Pulando.")
        return []

    user_prompt = f"""Portal: {portal}
Subject: {email.get('subject', '')}
From: {email.get('from', '')}
Date: {email.get('date', '')}

Email content:
{body}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text
        clean = clean_json_response(raw_text)
        jobs = json.loads(clean)

        # Garante que portal e source_email_id estejam preenchidos
        for job in jobs:
            job["portal"] = portal
            job["source_email_id"] = email["id"]

        return jobs

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON inválido no email {email['id']}: {e}")
        print(f"     Resposta bruta: {raw_text[:200]}")
        return []
    except Exception as e:
        print(f"  ❌ Erro ao parsear email {email['id']}: {e}")
        return []


def parse_all_emails(emails: list[dict]) -> list[dict]:
    """
    Parseia todos os emails e retorna lista consolidada de vagas.
    """
    all_jobs = []
    total = len(emails)

    for i, email in enumerate(emails, 1):
        subject_preview = email.get("subject", "")[:55]
        print(f"[{i}/{total}] Parseando: {subject_preview}...")

        jobs = parse_email(email)
        print(f"        → {len(jobs)} vaga(s) extraída(s)")
        all_jobs.extend(jobs)

    return all_jobs


if __name__ == "__main__":
    import sys

    input_file = "digests/raw_emails_full.json"

    if not os.path.exists(input_file):
        print(f"Arquivo não encontrado: {input_file}")
        print("Rode primeiro: python src/email_ingestor.py")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        emails = json.load(f)

    print(f"Parseando {len(emails)} emails...\n")
    jobs = parse_all_emails(emails)

    os.makedirs("digests", exist_ok=True)
    output = "digests/parsed_jobs_latest.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(jobs)} vagas extraídas → {output}")

    # Preview rápido
    if jobs:
        print("\nPrimeiras vagas:")
        for j in jobs[:5]:
            print(f"  • {j.get('empresa', 'N/A')} — {j.get('titulo', 'N/A')} ({j.get('localizacao', '?')})")
