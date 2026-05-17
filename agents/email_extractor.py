"""
email_extractor.py  —  Extrai email de contato do recrutador
Procura em descrição de vaga, usando padrões comuns e Claude
"""

import re
import anthropic

client = anthropic.Anthropic()

# Padrões comuns de email
EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# Padrões de contexto (pra ignorar emails gerais)
CONTACT_KEYWORDS = [
    'contact', 'contato', 'reach', 'email', 'apply', 'candidat', 'recruiter',
    'hiring', 'hr', 'human resources', 'interview', 'application', 'submit',
    'send your', 'send us', 'apply to', 'apply via', 'apply by', 'send your application'
]


def extract_emails_from_text(text: str) -> list[str]:
    """Extrai todos os emails de um texto usando regex."""
    if not text:
        return []
    return list(set(re.findall(EMAIL_REGEX, text)))


def is_contact_email(email: str, context: str) -> bool:
    """
    Verifica se um email parece ser de contato (não genérico como info@, support@, etc)
    """
    generic_prefixes = ['info@', 'support@', 'hello@', 'no-reply@', 'noreply@', 'no_reply@']
    
    email_lower = email.lower()
    
    # Rejeita emails genéricos
    for prefix in generic_prefixes:
        if email_lower.startswith(prefix):
            return False
    
    # Procura por keywords de contato no contexto próximo
    context_lower = context.lower()
    for keyword in CONTACT_KEYWORDS:
        if keyword in context_lower:
            return True
    
    return False


def extract_recruiter_email(job_description: str, empresa: str, titulo: str) -> str | None:
    """
    Extrai email de contato do recrutador usando:
    1. Regex + heurística
    2. Claude (como fallback)
    """
    
    if not job_description:
        return None
    
    # PASSO 1: Regex + Context
    emails = extract_emails_from_text(job_description)
    
    for email in emails:
        if is_contact_email(email, job_description):
            return email
    
    # PASSO 2: Se não achou, tenta Claude
    # (mais caro, mas mais preciso)
    if not emails:
        # Nenhum email encontrado
        return None
    
    # Se tem emails mas nenhum parece ser de contato, usa Claude
    try:
        prompt = f"""
Extract the recruiter/hiring contact email from this job description.
Return ONLY the email address, or "NONE" if not found.

COMPANY: {empresa}
JOB TITLE: {titulo}

JOB DESCRIPTION:
{job_description[:2000]}  # Limita tamanho

Return format: email@example.com or NONE
"""
        
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = response.content[0].text.strip()
        
        if result.lower() != "none" and "@" in result:
            return result
    
    except Exception as e:
        print(f"  ⚠️  Erro ao extrair email com Claude: {e}")
    
    return None


if __name__ == "__main__":
    # Teste
    test_description = """
    Position: Data Analyst
    
    We're hiring! Please send your CV to: john.smith@company.com or apply via our portal.
    
    For questions, contact: hr@company.com
    
    Apply by sending your application to hiring@company.com
    """
    
    email = extract_recruiter_email(test_description, "Company XYZ", "Data Analyst")
    print(f"Found recruiter email: {email}")
