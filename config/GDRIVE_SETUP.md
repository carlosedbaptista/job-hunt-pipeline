# Google Drive Upload Setup

The pipeline can automatically upload the generated CVs and Cover Letters to Google Drive, organized by folder (`Company - Role`).

## 1. Create a Service Account (Google Cloud Console)

1. Go to https://console.cloud.google.com/
2. Create a new project (or use an existing one)
3. Enable the **Google Drive API**:
   - Menu ≡ → APIs & Services → Library
   - Search "Google Drive API" → Enable
4. Create a Service Account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Give it a name (e.g. `job-hunt-pipeline`)
   - Role: `Editor` (or `Owner`)
   - Create and download a JSON key: Keys → Add Key → JSON

## 2. Configure the Drive Folder

1. In Google Drive, create a root folder (e.g. `Job Hunt Pipeline`)
2. Share that folder with the **Service Account's email** (found in the JSON, field `client_email`)
3. Grant **Editor** permission
4. Copy the **folder ID** from the URL:
   - `https://drive.google.com/drive/folders/1ABC...xyz` → ID = `1ABC...xyz`

## 3. Local Configuration

Option A - JSON file:
```bash
# Move the downloaded JSON key
mv your-key.json config/gdrive_credentials.json

# Set the folder ID in .env
echo "GDRIVE_PARENT_FOLDER_ID=1ABC...xyz" >> .env
```

Option B - Environment variable (recommended for CI):
```bash
# Base64-encode the JSON key
cat your-key.json | base64 -w 0

# Add to .env
echo "GDRIVE_CREDENTIALS_JSON_B64=<base64_of_the_json>" >> .env
echo "GDRIVE_PARENT_FOLDER_ID=1ABC...xyz" >> .env
```

## 4. Test

```bash
cd job-hunt-pipeline
python src/gdrive_uploader.py
```

If you see `[GDrive] Connected as: ...`, it's working.

## 5. GitHub Actions (CI)

In the repository, go to Settings → Secrets and variables → Actions → New repository secret:

1. `GDRIVE_CREDENTIALS_JSON_B64` = the JSON key content, base64-encoded
2. `GDRIVE_PARENT_FOLDER_ID` = the Drive folder ID

The workflow is already configured to use these variables.
