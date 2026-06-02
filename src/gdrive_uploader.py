"""
gdrive_uploader.py  —  Upload de CVs e CLs para Google Drive
Organiza por pasta:  Job Hunt Pipeline / {Empresa} - {Cargo} / [arquivos]

Setup:
  1. Crie uma Service Account em https://console.cloud.google.com/
  2. Ative a Google Drive API
  3. Baixe a chave JSON e salve como config/gdrive_credentials.json
  4. Crie uma pasta no Drive, compartilhe com o email da Service Account (Editor)
  5. Copie o ID da pasta para GDRIVE_PARENT_FOLDER_ID (env var ou .env)

Em CI (GitHub Actions):
  - Coloque o conteudo do JSON em um Secret GDRIVE_CREDENTIALS_JSON
  - Coloque o ID da pasta em GDRIVE_PARENT_FOLDER_ID
"""
import os
import json
import base64
from pathlib import Path

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
PARENT_FOLDER_ENV = "GDRIVE_PARENT_FOLDER_ID"


def _get_credentials():
    """Carrega credenciais da Service Account."""
    # 1. Tenta via env var (base64 encoded JSON) — util para GitHub Actions
    env_b64 = os.environ.get("GDRIVE_CREDENTIALS_JSON_B64")
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode("utf-8")
            info = json.loads(decoded)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"[GDrive] Erro ao decodificar GDRIVE_CREDENTIALS_JSON_B64: {e}")

    # 2. Tenta via env var (raw JSON string)
    env_raw = os.environ.get("GDRIVE_CREDENTIALS_JSON")
    if env_raw:
        try:
            info = json.loads(env_raw)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"[GDrive] Erro ao parsear GDRIVE_CREDENTIALS_JSON: {e}")

    # 3. Tenta via arquivo
    if os.path.exists(CREDENTIALS_PATH):
        try:
            return service_account.Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        except Exception as e:
            print(f"[GDrive] Erro ao ler {CREDENTIALS_PATH}: {e}")

    return None


def _get_drive_service():
    """Retorna o servico do Google Drive."""
    creds = _get_credentials()
    if not creds:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_folder(service, name, parent_id=None):
    """Procura uma pasta pelo nome. Retorna o ID ou None."""
    query = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    try:
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=10).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"[GDrive] Erro ao procurar pasta '{name}': {e}")
        return None


def _create_folder(service, name, parent_id=None):
    """Cria uma pasta no Drive. Retorna o ID."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id] if parent_id else []
    }
    try:
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder["id"]
    except Exception as e:
        print(f"[GDrive] Erro ao criar pasta '{name}': {e}")
        return None


def _get_or_create_folder(service, name, parent_id=None):
    """Procura pasta; se nao existir, cria. Retorna ID."""
    folder_id = _find_folder(service, name, parent_id)
    if folder_id:
        return folder_id
    return _create_folder(service, name, parent_id)


def _find_file(service, name, parent_id):
    """Procura arquivo pelo nome dentro de uma pasta. Retorna ID ou None."""
    query = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    try:
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=5).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"[GDrive] Erro ao procurar arquivo '{name}': {e}")
        return None


def _upload_file(service, local_path, parent_id, mime_type="application/pdf"):
    """Faz upload de um arquivo. Se ja existir, atualiza. Retorna o ID."""
    name = os.path.basename(local_path)
    file_id = _find_file(service, name, parent_id)

    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

    try:
        if file_id:
            # Atualiza arquivo existente
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"  [GDrive] Atualizado: {name}")
            return file_id
        else:
            # Cria novo
            metadata = {"name": name, "parents": [parent_id]}
            file = service.files().create(body=metadata, media_body=media, fields="id").execute()
            print(f"  [GDrive] Upload: {name}")
            return file["id"]
    except Exception as e:
        print(f"  [GDrive] Erro no upload de '{name}': {e}")
        return None


def upload_cv_cl(folder_local_path, company, title):
    """
    Faz upload dos PDFs de CV e CL de uma pasta local para o Google Drive.
    
    Args:
        folder_local_path: caminho da pasta local (ex: generated_docs/Company_Job)
        company: nome da empresa
        title: titulo do cargo
    
    Returns:
        dict com ids dos arquivos ou None em caso de erro
    """
    if not GDRIVE_AVAILABLE:
        print("[GDrive] Bibliotecas do Google nao instaladas. Instale: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        return None

    parent_folder_id = os.environ.get(PARENT_FOLDER_ENV, "")
    if not parent_folder_id:
        print(f"[GDrive] Variavel {PARENT_FOLDER_ENV} nao configurada. Skipping upload.")
        return None

    service = _get_drive_service()
    if not service:
        print("[GDrive] Nao foi possivel autenticar. Verifique as credenciais.")
        return None

    # Nome da subpasta: "Empresa - Cargo"
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
