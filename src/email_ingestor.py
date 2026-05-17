"""
email_ingestor.py
Busca emails de alertas de vagas das últimas N horas via Gmail API.
"""

import os
import base64
import json
import pickle
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Ajuste estes remetentes conforme seus alertas reais no Gmail
JOB_ALERT_SENDERS = [
    "jobs.ch",
    "jobup.ch",
    "linkedin.com",
    "indeed.com",
    "job-room.ch",
    "glassdoor.com",
    "xing.com",
    "swissdevjobs.ch",
]


def get_gmail_service(credentials_path="credentials.json", token_path="token.pickle"):
    """Autentica e retorna o serviço Gmail API."""
    creds = None

    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


def decode_part(data: str) -> str:
    """Decodifica base64url para string."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def extract_body(payload: dict) -> tuple[str, str]:
    """Extrai HTML e texto plano do payload do email."""
    html_body = ""
    text_body = ""

    def walk(parts):
        nonlocal html_body, text_body
        for part in parts:
            mime = part.get("mimeType", "")
            if "parts" in part:
                walk(part["parts"])
            elif mime == "text/html" and not html_body:
                data = part.get("body", {}).get("data", "")
                if data:
                    html_body = decode_part(data)
            elif mime == "text/plain" and not text_body:
                data = part.get("body", {}).get("data", "")
                if data:
                    text_body = decode_part(data)

    if "parts" in payload:
        walk(payload["parts"])
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            mime = payload.get("mimeType", "")
            if mime == "text/html":
                html_body = decode_part(data)
            else:
                text_body = decode_part(data)

    return html_body, text_body


def build_query(hours_back: int) -> str:
    """
    Monta a query de busca para o Gmail.
    Tenta primeiro pelo label 'job-alerts'. Se não tiver esse label,
    usa os remetentes conhecidos como fallback.
    """
    after_ts = int(
        (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp()
    )

    senders = " OR ".join(f"from:{s}" for s in JOB_ALERT_SENDERS)
    return f"({senders}) after:{after_ts}"


def fetch_job_alert_emails(hours_back: int = 24, max_results: int = 50) -> list[dict]:
    """
    Busca emails de alertas de vagas nas últimas N horas.
    Retorna lista de dicts com metadados e corpo do email.
    """
    service = get_gmail_service()
    query = build_query(hours_back)

    print(f"Query Gmail: {query}")

    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    messages = result.get("messages", [])

    if not messages:
        print(f"Nenhum email de alerta encontrado nas últimas {hours_back}h.")
        return []

    print(f"Encontrados {len(messages)} emails. Extraindo conteúdo...")

    emails = []
    for i, msg_ref in enumerate(messages):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="full")
            .execute()
        )

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        html_body, text_body = extract_body(msg["payload"])

        email = {
            "id": msg["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "html_body": html_body,
            "text_body": text_body,
        }
        emails.append(email)

        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(messages)} emails processados...")

    print(f"Total: {len(emails)} emails extraídos.")
    return emails


if __name__ == "__main__":
    os.makedirs("digests", exist_ok=True)

    emails = fetch_job_alert_emails(hours_back=24)

    output_path = f"digests/raw_emails_latest.json"
    with open(output_path, "w", encoding="utf-8") as f:
        # Salva sem html_body para inspeção rápida (pode ser grande)
        preview = [
            {k: v for k, v in e.items() if k not in ("html_body", "text_body")}
            for e in emails
        ]
        json.dump(preview, f, ensure_ascii=False, indent=2)

    # Salva completo num arquivo separado
    with open("digests/raw_emails_full.json", "w", encoding="utf-8") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(emails)} emails salvos em digests/")
