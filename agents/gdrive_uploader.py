#!/usr/bin/env python3
"""
gdrive_uploader.py — Uploads generated CVs and Cover Letters to Google Drive
Uses Google Drive API v3 with Service Account credentials.

Prerequisites:
1. Create Service Account in Google Cloud Console
2. Enable Google Drive API v3
3. Download JSON key and add as GitHub Secret: GOOGLE_CREDENTIALS_JSON
4. Share target Drive folder with the Service Account email

Env vars:
  GOOGLE_CREDENTIALS_JSON — Service account JSON (inline)
  GOOGLE_DRIVE_FOLDER_ID  — Optional: root folder ID (default: creates 'Job Hunt - Carlos')
"""

import json
import os
import sys
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from io import BytesIO

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    """Builds Drive service from service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        print("⚠️  GOOGLE_CREDENTIALS_JSON not set. Skipping Drive upload.")
        return None

    try:
        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return service
    except Exception as e:
        print(f"❌ Error creating Drive service: {e}")
        return None


def ensure_folder(service, name, parent_id=None):
    """Creates a folder if it doesn't exist, returns folder ID."""
    query = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id] if parent_id else [],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_text_file(service, parent_id, filename, content, mime_type="text/plain"):
    """Uploads a text file to Google Drive."""
    metadata = {"name": filename, "parents": [parent_id]}
    media = MediaIoBaseUpload(BytesIO(content.encode("utf-8")), mimetype=mime_type)
    file = service.files().create(body=metadata, media_body=media, fields="id, name").execute()
    return file["id"]


def upload_cv_cl_files():
    """Main upload function: reads CV/CL JSON and uploads to Drive."""
    service = get_drive_service()
    if not service:
        return False

    date_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Root folder: "Job Hunt - Carlos"
    root_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not root_folder_id:
        root_folder_id = ensure_folder(service, "Job Hunt - Carlos")
        print(f"📁 Root folder: Job Hunt - Carlos (ID: {root_folder_id})")

    # Date subfolder
    date_folder_id = ensure_folder(service, date_str, root_folder_id)
    print(f"📁 Date folder: {date_str} (ID: {date_folder_id})")

    # Read cover letters
    cl_file = "digests/cover_letters_latest.json"
    cv_file = "digests/tailored_cvs_latest.json"

    uploaded = 0
    errors = 0

    # Upload Cover Letters
    if os.path.exists(cl_file):
        with open(cl_file, "r", encoding="utf-8") as f:
            cover_letters = json.load(f)

        for item in cover_letters:
            empresa = item.get("empresa", "Unknown").replace("/", "-")
            titulo = item.get("titulo", "Unknown").replace("/", "-")[:60]
            score = item.get("score", 0)
            cl_text = item.get("cover_letter", "")
            url = item.get("url", "")

            if not cl_text:
                continue

            # Create subfolder per job
            job_folder_name = f"{score:02d} - {empresa} - {titulo}"
            job_folder_id = ensure_folder(service, job_folder_name, date_folder_id)

            # Upload cover letter
            try:
                cl_content = f"""COVER LETTER
Generated: {timestamp}
Company: {empresa}
Title: {titulo}
Score: {score}/100
URL: {url}

---

{cl_text}
"""
                upload_text_file(service, job_folder_id, f"Cover Letter - {empresa}.txt", cl_content)
                print(f"  ✅ CL uploaded: {empresa} — {titulo} (score: {score})")
                uploaded += 1
            except Exception as e:
                print(f"  ❌ CL upload failed: {empresa} — {e}")
                errors += 1

    # Upload Tailored CVs
    if os.path.exists(cv_file):
        with open(cv_file, "r", encoding="utf-8") as f:
            cvs = json.load(f)

        for item in cvs:
            empresa = item.get("empresa", "Unknown").replace("/", "-")
            titulo = item.get("titulo", "Unknown").replace("/", "-")[:60]
            score = item.get("score", 0)
            cv_text = item.get("cv_tailored", "")
            url = item.get("url", "")

            if not cv_text:
                continue

            job_folder_name = f"{score:02d} - {empresa} - {titulo}"
            job_folder_id = ensure_folder(service, job_folder_name, date_folder_id)

            try:
                cv_content = f"""TAILORED CV
Generated: {timestamp}
Company: {empresa}
Title: {titulo}
Score: {score}/100
URL: {url}

---

{cv_text}
"""
                upload_text_file(service, job_folder_id, f"CV - {empresa}.txt", cv_content)
                print(f"  ✅ CV uploaded: {empresa} — {titulo} (score: {score})")
                uploaded += 1
            except Exception as e:
                print(f"  ❌ CV upload failed: {empresa} — {e}")
                errors += 1

    print(f"\n📊 Upload summary: {uploaded} files uploaded, {errors} errors")
    return errors == 0


if __name__ == "__main__":
    success = upload_cv_cl_files()
    sys.exit(0 if success else 1)
