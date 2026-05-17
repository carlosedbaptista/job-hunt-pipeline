"""
followup_writer.py  —  Gera follow-ups personalizados com Claude Sonnet
Usado pra vagas sem resposta > 7 dias
"""

import json
import os
import sys
import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

client = anthropic.Anthropic()

FOLLOWUP_SYSTEM_PROMPT = """You are writing a professional follow-up email for a job application.

GUIDELINES:
- Respectful and professional tone
- Brief (150-200 words max)
- Reference the original application
- Express continued interest
- Suggest next steps
- Do NOT be pushy or demanding

Language: English (C1 level)

Return ONLY the email body (no subject line, no greeting, no signature yet)."""


def generate_followup(
    empresa: str,
    titulo: str,
    dias_passados: int,
    original_application_date: str,
) -> str | None:
    """
    Gera um follow-up personalizado.
    
    Args:
        empresa: Nome da empresa
        titulo: Título da vaga
        dias_passados: Quantos dias passaram
        original_application_date: Data da aplicação original
    """
    
    prompt = f"""Generate a professional follow-up email for this job application:

COMPANY: {empresa}
JOB TITLE: {titulo}
DAYS SINCE APPLICATION: {dias_passados}
ORIGINAL APPLICATION DATE: {original_application_date}

The follow-up should:
1. Reference the original application
2. Reiterate interest in the position
3. Politely ask about the status
4. Offer to provide additional information
5. Suggest next steps

Keep it concise and professional."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=FOLLOWUP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text.strip()
    
    except Exception as e:
        print(f"❌ Erro ao gerar follow-up: {e}")
        return None


def generate_followup_email_package(application: dict) -> dict | None:
    """
    Gera pacote completo de follow-up (assunto + corpo).
    
    Args:
        application: Dicionário com dados da aplicação do banco
    """
    
    empresa = application.get("empresa", "Unknown")
    titulo = application.get("titulo", "Unknown")
    dias_passados = application.get("dias_sem_resposta", 0)
    data_aplicacao = application.get("date_applied", "Unknown")
    
    # Gera corpo do email
    body = generate_followup(empresa, titulo, dias_passados, data_aplicacao)
    
    if not body:
        return None
    
    # Gera assunto
    subject = f"Following up: {titulo} at {empresa}"
    
    return {
        "subject": subject,
        "body": body,
        "dias_passados": dias_passados,
        "empresa": empresa,
        "titulo": titulo,
    }


if __name__ == "__main__":
    # Teste
    test_app = {
        "empresa": "Sika AG",
        "titulo": "Data Analyst",
        "dias_sem_resposta": 10,
        "date_applied": "2026-05-07"
    }
    
    result = generate_followup_email_package(test_app)
    
    if result:
        print(f"Subject: {result['subject']}\n")
        print(f"Body:\n{result['body']}")
    else:
        print("❌ Erro ao gerar follow-up")
