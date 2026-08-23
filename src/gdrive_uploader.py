"""
gdrive_uploader.py  —  Upload CVs and CLs to Google Drive
Supports: Service Account (CI) or OAuth2 refresh token (local/personal)
Organizes by folder:  Job Hunt Pipeline / {Company} - {Title} / [files]

Use OAuth2. The Service Account path is kept only as a fallback and CANNOT
work against a personal Drive: Google reports a Service Account's quota as
{"limit": "0"}, so it owns no bytes and every upload answers
403 storageQuotaExceeded. Sharing a folder with it grants the right to enter,
never the right to store. It would work only inside a Workspace Shared Drive,
where the drive owns the files.

Service Account setup (Shared Drive only):
  1. Create a Service Account at https://console.cloud.google.com/
  2. Enable the Google Drive API
  3. Download the JSON key and save it as config/gdrive_credentials.json
  4. Share a SHARED DRIVE folder with the Service Account (Editor)
  5. Set GDRIVE_PARENT_FOLDER_ID

OAuth2 setup (what this project uses -- the candidate owns the files):
  1. Create OAuth2 credentials (Desktop app) in the Google Cloud Console
  2. Run: python config/setup_oauth2.py
  3. Authorize in the browser and paste the code
  4. The refresh token will be saved to config/gdrive_refresh_token.json

In CI (GitHub Actions):
  - Service Account: GDRIVE_CREDENTIALS_JSON_B64 + GDRIVE_PARENT_FOLDER_ID
  - OAuth2: GDRIVE_REFRESH_TOKEN_B64 + GDRIVE_PARENT_FOLDER_ID
"""
import os
import json
import base64
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Google Drive API
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2 import service_account
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False


# drive.file, NOT drive: the app can only see and touch what it created
# itself. This refresh token lives in a GitHub Secret, and the full `drive`
# scope would make a leak cost the candidate his entire personal Drive
# instead of a folder of job PDFs he already sends to recruiters.
#
# The consequence is that a folder created by hand in the browser is
# INVISIBLE here, which is why the root folder is found-or-created by the
# app itself (see _resolve_root_folder) instead of being handed to it.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_PATH = "config/gdrive_credentials.json"
REFRESH_TOKEN_PATH = "config/gdrive_refresh_token.json"
PARENT_FOLDER_ENV = "GDRIVE_PARENT_FOLDER_ID"
# Name of the app-owned root. Everything the pipeline writes lives under it,
# one subfolder per job: "Job Hunt Pipeline / Avaloq - AI Software Engineer".
ROOT_FOLDER_NAME = os.environ.get("GDRIVE_ROOT_FOLDER_NAME", "Job Hunt Pipeline")


def _get_service_account_credentials():
    """Load Service Account credentials."""
    env_b64 = os.environ.get("GDRIVE_CREDENTIALS_JSON_B64")
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode("utf-8")
            info = json.loads(decoded)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"  [GDrive] Error decoding GDRIVE_CREDENTIALS_JSON_B64: {e}")

    env_raw = os.environ.get("GDRIVE_CREDENTIALS_JSON")
    if env_raw:
        try:
            info = json.loads(env_raw)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"  [GDrive] Error parsing GDRIVE_CREDENTIALS_JSON: {e}")

    if os.path.exists(CREDENTIALS_PATH):
        try:
            return service_account.Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        except Exception as e:
            print(f"  [GDrive] Error reading {CREDENTIALS_PATH}: {e}")
    return None


def _get_oauth2_credentials():
    """Load OAuth2 credentials via refresh token."""
    # Try via base64 env var
    env_b64 = os.environ.get("GDRIVE_REFRESH_TOKEN_B64")
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode("utf-8")
            data = json.loads(decoded)
            return _refresh_access_token(data)
        except Exception as e:
            print(f"  [GDrive] Error decoding GDRIVE_REFRESH_TOKEN_B64: {e}")

    # Try via file
    if not os.path.exists(REFRESH_TOKEN_PATH):
        return None
    try:
        with open(REFRESH_TOKEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _refresh_access_token(data)
    except Exception as e:
        print(f"  [GDrive] Error reading refresh token: {e}")
        return None


def _refresh_access_token(data):
    """Use refresh token to obtain an access token. Returns dict with access_token."""
    token_uri = data.get("token_uri", "https://oauth2.googleapis.com/token")
    payload = urllib.parse.urlencode({
        "client_id": data["client_id"],
        "client_secret": data["client_secret"],
        "refresh_token": data["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(token_uri, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {
                "access_token": result["access_token"],
                "token_type": result.get("token_type", "Bearer"),
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        hint = ""
        if "invalid_grant" in body:
            # Learned the hard way on 2026-08-23: revoking an OLD token for
            # the same user+client kills the CURRENT one too -- Google revokes
            # the whole grant, not the individual token. Do not "tidy up" old
            # tokens; just let them expire.
            hint = (" -- the token was revoked or expired. Note that revoking any token "
                    "for this client revokes ALL of them, including the current one. "
                    "Re-authorise with `python config/setup_oauth2.py`.")
        print(f"  [GDrive] Error refreshing token: HTTP {e.code} {body[:160]}{hint}")
        return None
    except Exception as e:
        print(f"  [GDrive] Error refreshing token: {e}")
        return None


def _get_drive_service():
    """The Drive service: OAuth2 if configured, Service Account otherwise.

    The fallback is deliberately NOT taken when OAuth2 is configured but
    fails. A Service Account authenticates perfectly and then cannot upload
    anything to a personal Drive -- its quota is {"limit": "0"} -- so falling
    back turns a clear "your token died" into a confusing 403 at upload time,
    three log lines later. That is exactly how a dead refresh token went
    unnoticed on 2026-08-23.
    """
    if not GDRIVE_AVAILABLE:
        return None

    oauth2_configured = bool(os.environ.get("GDRIVE_REFRESH_TOKEN_B64")
                             or os.path.exists(REFRESH_TOKEN_PATH))
    if oauth2_configured:
        oauth2 = _get_oauth2_credentials()
        if oauth2:
            from google.oauth2.credentials import Credentials
            gcreds = Credentials(token=oauth2["access_token"], scopes=SCOPES)
            return build("drive", "v3", credentials=gcreds, cache_discovery=False)
        print("  [GDrive] OAuth2 is configured but the refresh token did not work. "
              "Re-run `python config/setup_oauth2.py` and update GDRIVE_REFRESH_TOKEN_B64. "
              "NOT falling back to the Service Account: it can authenticate but owns no "
              "storage, so it would fail again at upload with a less obvious message.")
        return None

    # Service Account: only ever usable against a Workspace Shared Drive.
    creds = _get_service_account_credentials()
    if creds:
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    return None


def _escape_drive_query_value(value: str) -> str:
    """Escapes a value for safe interpolation into a Drive API `q=` filter
    string (per Google's documented convention: backslash-escape `\\` and
    `'`). Folder/file names here derive from scraped job postings (company,
    title) -- untrusted, external input -- so an apostrophe in a company
    name (or a deliberately crafted one) must not be able to break out of
    the quoted value and alter the query."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_folder(service, name, parent_id=None):
    safe_name = _escape_drive_query_value(name)
    query = f"mimeType='application/vnd.google-apps.folder' and name='{safe_name}' and trashed=false"
    if parent_id:
        query += f" and '{_escape_drive_query_value(parent_id)}' in parents"
    try:
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=10, supportsAllDrives=True).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"  [GDrive] Error searching for folder '{name}': {e}")
        return None


def _create_folder(service, name, parent_id=None):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id] if parent_id else []
    }
    try:
        folder = service.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
        return folder["id"]
    except Exception as e:
        print(f"  [GDrive] Error creating folder '{name}': {e}")
        return None


def _get_or_create_folder(service, name, parent_id=None):
    folder_id = _find_folder(service, name, parent_id)
    if folder_id:
        return folder_id
    return _create_folder(service, name, parent_id)


def _find_file(service, name, parent_id):
    query = f"name='{_escape_drive_query_value(name)}' and '{_escape_drive_query_value(parent_id)}' in parents and trashed=false"
    try:
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=5, supportsAllDrives=True).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"  [GDrive] Error searching for file '{name}': {e}")
        return None


def _upload_file(service, local_path, parent_id, mime_type="application/pdf"):
    name = os.path.basename(local_path)
    file_id = _find_file(service, name, parent_id)
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

    try:
        if file_id:
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"    [GDrive] Updated: {name}")
            return file_id
        else:
            metadata = {"name": name, "parents": [parent_id]}
            file = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"    [GDrive] Upload: {name}")
            return file["id"]
    except Exception as e:
        print(f"    [GDrive] Error uploading '{name}': {e}")
        return None


def _resolve_root_folder(service):
    """The folder everything is written under.

    Prefers GDRIVE_PARENT_FOLDER_ID when the app can actually reach it, which
    is the case for a folder it created before, or for any folder at all under
    the old full-`drive` scope. Under drive.file a folder created by hand in
    the browser is invisible, so the id is silently useless -- hence the
    reachability check rather than trusting the variable.

    Falls back to finding, or creating, ROOT_FOLDER_NAME. Once the app owns
    that folder it stays visible on every later run.
    """
    configured = os.environ.get(PARENT_FOLDER_ENV, "")
    if configured:
        try:
            service.files().get(fileId=configured, fields="id",
                                supportsAllDrives=True).execute()
            return configured
        except Exception:
            print(f"  [GDrive] {PARENT_FOLDER_ENV} is set but this app cannot see that "
                  f"folder (expected under the drive.file scope if it was created by "
                  f"hand). Using its own '{ROOT_FOLDER_NAME}' folder instead.")

    return _get_or_create_folder(service, ROOT_FOLDER_NAME, None)


def upload_cv_cl(folder_local_path, company, title):
    """Uploads the CV and CL PDFs, into "{root}/{Company} - {Title}".

    Returns {"files": {filename: file_id}, "folder_link": url} -- the link is
    what agents/doc_generator.py records in the digest manifest, so the daily
    e-mail can offer a download instead of carrying the PDFs as attachments.
    Returns None when the upload could not even be attempted.
    """
    if not GDRIVE_AVAILABLE:
        print("[GDrive] Google libraries not installed.")
        return None

    service = _get_drive_service()
    if not service:
        print("[GDrive] Could not authenticate. Check the credentials.")
        return None

    parent_folder_id = _resolve_root_folder(service)
    if not parent_folder_id:
        print("[GDrive] No usable root folder. Skipping upload.")
        return None

    safe_company = company.strip()[:40]
    safe_title = title.strip()[:40]
    subfolder_name = f"{safe_company} - {safe_title}"

    print(f"[GDrive] Ensuring folder: {subfolder_name}")
    subfolder_id = _get_or_create_folder(service, subfolder_name, parent_folder_id)
    if not subfolder_id:
        print(f"[GDrive] Failed to create folder '{subfolder_name}'")
        return None

    folder_link = f"https://drive.google.com/drive/folders/{subfolder_id}"
    files = {}
    folder = Path(folder_local_path)
    # .docx as well as .pdf: the editable copies belong in Drive too, since
    # that is where the candidate goes to fix a sentence before sending.
    pdf_files = sorted(f for f in folder.iterdir()
                       if f.suffix.lower() in (".pdf", ".docx"))

    if not pdf_files:
        print(f"[GDrive] No document found in {folder_local_path}")
        return {"files": files, "folder_link": folder_link}

    for pdf in pdf_files:
        fid = _upload_file(service, str(pdf), subfolder_id)
        if fid:
            files[pdf.name] = fid

    # Only advertise the folder if something actually landed in it. A link to
    # an empty folder is worse than no link: the digest would tell the
    # candidate his documents are waiting somewhere they are not.
    return {"files": files, "folder_link": folder_link if files else ""}


def test_connection():
    """Test the Google Drive connection."""
    if not GDRIVE_AVAILABLE:
        print("[GDrive] Libraries not installed.")
        return False

    service = _get_drive_service()
    if not service:
        print("[GDrive] Authentication failed.")
        return False

    try:
        about = service.about().get(fields="user(displayName), storageQuota").execute()
        user = about.get("user", {}).get("displayName", "Unknown")
        print(f"[GDrive] Connected as: {user}")
        return True
    except Exception as e:
        print(f"[GDrive] Error testing connection: {e}")
        return False


if __name__ == "__main__":
    test_connection()
