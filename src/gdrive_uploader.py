"""
gdrive_uploader.py  —  Upload de CVs e CLs para Google Drive
Suporta: Service Account (CI) ou OAuth2 refresh token (local/pessoal)
Organiza por pasta:  Job Hunt Pipeline / {Empresa} - {Cargo} / [arquivos]

Setup Service Account:
  1. Crie uma Service Account em https://console.cloud.google.com/
  2. Ative a Google Drive API
  3. Baixe a chave JSON e salve como config/gdrive_credentials.json
  4. Compartilhe uma pasta do seu Drive com a Service Account (Editor)
  5. Configure GDRIVE_PARENT_FOLDER_ID

Setup OAuth2 (fallback para contas pessoais sem Workspace):
  1. Crie credenciais OAuth2 (Desktop app) no Google Cloud Console
  2. Rode: python config/setup_oauth2.py
  3. Autorize no navegador e cole o code
  4. O refresh token sera salvo em config/gdrive_refresh_token.json

Em CI (GitHub Actions):
  - Service Account: GDRIVE_CREDENTIALS_JSON_B64 + GDRIVE_PARENT_FOLDER_ID
  - OAuth2: GDRIVE_REFRESH_TOKEN_B64 + GDRIVE_PARENT_FOLDER_ID
"""
import os
import json
import base64
import urllib.request
import urllib.parse
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


SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDENTIALS_PATH = "config/gdrive_credentials.json"
REFRESH_TOKEN_PATH = "config/gdrive_refresh_token.json"
PARENT_FOLDER_ENV = "GDRIVE_PARENT_FOLDER_ID"


def _get_service_account_credentials():
    """Carrega credenciais da Service Account."""
    env_b64 = os.environ.get("GDRIVE_CREDENTIALS_JSON_B64")
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode("utf-8")
            info = json.loads(decoded)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"  [GDrive] Erro ao decodificar GDRIVE_CREDENTIALS_JSON_B64: {e}")

    env_raw = os.environ.get("GDRIVE_CREDENTIALS_JSON")
    if env_raw:
        try:
            info = json.loads(env_raw)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"  [GDrive] Erro ao parsear GDRIVE_CREDENTIALS_JSON: {e}")

    if os.path.exists(CREDENTIALS_PATH):
        try:
            return service_account.Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        except Exception as e:
            print(f"  [GDrive] Erro ao ler {CREDENTIALS_PATH}: {e}")
    return None


def _get_oauth2_credentials():
    """Carrega credenciais OAuth2 via refresh token."""
    # Tenta via env var base64
    env_b64 = os.environ.get("GDRIVE_REFRESH_TOKEN_B64")
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode("utf-8")
            data = json.loads(decoded)
            return _refresh_access_token(data)
        except Exception as e:
            print(f"  [GDrive] Erro ao decodificar GDRIVE_REFRESH_TOKEN_B64: {e}")

    # Tenta via arquivo
    if not os.path.exists(REFRESH_TOKEN_PATH):
        return None
    try:
        with open(REFRESH_TOKEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _refresh_access_token(data)
    except Exception as e:
        print(f"  [GDrive] Erro ao ler refresh token: {e}")
        return None


def _refresh_access_token(data):
    """Usa refresh token para obter access token. Retorna dict com access_token."""
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
    except Exception as e:
        print(f"  [GDrive] Erro ao refresh token: {e}")
        return None


def _get_drive_service():
    """Retorna o servico do Google Drive (tenta Service Account, depois OAuth2)."""
    if not GDRIVE_AVAILABLE:
        return None

    # Tenta OAuth2 primeiro (funciona para contas pessoais)
    oauth2 = _get_oauth2_credentials()
    if oauth2:
        from google.oauth2.credentials import Credentials
        gcreds = Credentials(token=oauth2["access_token"], scopes=SCOPES)
        return build("drive", "v3", credentials=gcreds, cache_discovery=False)

    # Fallback para Service Account (requer Workspace/Shared Drive)
    creds = _get_service_account_credentials()
    if creds:
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    return None


def _find_folder(service, name, parent_id=None):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    try:
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=10, supportsAllDrives=True).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"  [GDrive] Erro ao procurar pasta '{name}': {e}")
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
        print(f"  [GDrive] Erro ao criar pasta '{name}': {e}")
        return None


def _get_or_create_folder(service, name, parent_id=None):
    folder_id = _find_folder(service, name, parent_id)
    if folder_id:
        return folder_id
    return _create_folder(service, name, parent_id)


def _find_file(service, name, parent_id):
    query = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    try:
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=5, supportsAllDrives=True).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"  [GDrive] Erro ao procurar arquivo '{name}': {e}")
        return None


def _upload_file(service, local_path, parent_id, mime_type="application/pdf"):
    name = os.path.basename(local_path)
    file_id = _find_file(service, name, parent_id)
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

    try:
        if file_id:
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"    [GDrive] Atualizado: {name}")
            return file_id
        else:
            metadata = {"name": name, "parents": [parent_id]}
            file = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"    [GDrive] Upload: {name}")
            return file["id"]
    except Exception as e:
        print(f"    [GDrive] Erro no upload de '{name}': {e}")
        return None


def upload_cv_cl(folder_local_path, company, title):
    """
    Faz upload dos PDFs de CV e CL para o Google Drive.
    Cria pasta: {Empresa} - {Cargo}
    """
    if not GDRIVE_AVAILABLE:
        print("[GDrive] Bibliotecas do Google nao instaladas.")
        return None

    parent_folder_id = os.environ.get(PARENT_FOLDER_ENV, "")
    if not parent_folder_id:
        print(f"[GDrive] Variavel {PARENT_FOLDER_ENV} nao configurada. Skipping upload.")
        return None

    service = _get_drive_service()
    if not service:
        print("[GDrive] Nao foi possivel autenticar. Verifique as credenciais.")
        return None

    safe_company = company.strip()[:40]
    safe_title = title.strip()[:40]
    subfolder_name = f"{safe_company} - {safe_title}"

    print(f"[GDrive] Garantindo pasta: {subfolder_name}")
    subfolder_id = _get_or_create_folder(service, subfolder_name, parent_folder_id)
    if not subfolder_id:
        print(f"[GDrive] Falha ao criar pasta '{subfolder_name}'")
        return None

    result = {}
    folder = Path(folder_local_path)
    pdf_files = sorted(folder.glob("*.pdf"))

    if not pdf_files:
        print(f"[GDrive] Nenhum PDF encontrado em {folder_local_path}")
        return result

    for pdf in pdf_files:
        fid = _upload_file(service, str(pdf), subfolder_id)
        if fid:
            result[pdf.name] = fid

    return result


def test_connection():
    """Testa a conexao com o Google Drive."""
    if not GDRIVE_AVAILABLE:
        print("[GDrive] Bibliotecas nao instaladas.")
        return False

    service = _get_drive_service()
    if not service:
        print("[GDrive] Falha na autenticacao.")
        return False

    try:
        about = service.about().get(fields="user(displayName), storageQuota").execute()
        user = about.get("user", {}).get("displayName", "Unknown")
        print(f"[GDrive] Conectado como: {user}")
        return True
    except Exception as e:
        print(f"[GDrive] Erro ao testar conexao: {e}")
        return False


if __name__ == "__main__":
    test_connection()
