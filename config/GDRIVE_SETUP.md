# Google Drive Upload Setup

O pipeline pode fazer upload automatico dos CVs e Cover Letters gerados para o Google Drive, organizados por pasta (`Empresa - Cargo`).

## 1. Criar Service Account (Google Cloud Console)

1. Acesse https://console.cloud.google.com/
2. Crie um novo projeto (ou use um existente)
3. Ative a **Google Drive API**:
   - Menu ≡ → APIs & Services → Library
   - Pesquise "Google Drive API" → Enable
4. Crie uma Service Account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - De um nome (ex: `job-hunt-pipeline`)
   - Role: `Editor` (ou `Owner`)
   - Crie e baixe uma chave JSON: Keys → Add Key → JSON

## 2. Configurar Pasta no Drive

1. No Google Drive, crie uma pasta raiz (ex: `Job Hunt Pipeline`)
2. Compartilhe essa pasta com o **email da Service Account** (encontrado no JSON, campo `client_email`)
3. De permissao de **Editor**
4. Copie o **ID da pasta** da URL:
   - `https://drive.google.com/drive/folders/1ABC...xyz` → ID = `1ABC...xyz`

## 3. Configuracao Local

Opcao A - Arquivo JSON:
```bash
# Copie o JSON baixado
mv sua-chave.json config/gdrive_credentials.json

# Configure o ID da pasta no .env
echo "GDRIVE_PARENT_FOLDER_ID=1ABC...xyz" >> .env
```

Opcao B - Variavel de ambiente (recomendado para CI):
```bash
# Codifique o JSON em base64
cat sua-chave.json | base64 -w 0

# Adicione ao .env
echo "GDRIVE_CREDENTIALS_JSON_B64=<base64_do_json>" >> .env
echo "GDRIVE_PARENT_FOLDER_ID=1ABC...xyz" >> .env
```

## 4. Testar

```bash
cd job-hunt-pipeline
python src/gdrive_uploader.py
```

Se aparecer `[GDrive] Conectado como: ...`, esta funcionando.

## 5. GitHub Actions (CI)

No repositorio, va em Settings → Secrets and variables → Actions → New repository secret:

1. `GDRIVE_CREDENTIALS_JSON_B64` = conteudo do JSON codificado em base64
2. `GDRIVE_PARENT_FOLDER_ID` = ID da pasta no Drive

O workflow ja esta configurado para usar essas variaveis.
