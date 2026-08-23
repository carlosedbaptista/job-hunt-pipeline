# Google Drive upload setup

The pipeline uploads the generated CV and cover letter (PDF and .docx) to
Google Drive, one folder per job:

```
Job Hunt Pipeline/
  BLP Digital AG - Internship - Engineering/
    CV_BLP_Digital_AG_Internship_-_Engineering.pdf
    CV_BLP_Digital_AG_Internship_-_Engineering.docx
    CL_BLP_Digital_AG_Internship_-_Engineering.pdf
    CL_BLP_Digital_AG_Internship_-_Engineering.docx
```

## Use OAuth2. A Service Account cannot work here.

This document used to describe a Service Account. That path is dead by
construction, and it cost real time to find out, so it is written down here.

A Service Account has **no storage of its own**. Asked directly, Google
reports its quota as:

```json
{"limit": "0", "usage": "0"}
```

Every file in Drive needs an owner, and the owner is charged for the bytes.
So the Service Account can authenticate, and it can list and read a folder
you shared with it, but every upload answers:

```
403 storageQuotaExceeded
"Service Accounts do not have storage quota. Leverage shared drives,
 or use OAuth delegation instead."
```

Sharing a folder with it grants the right to enter, never the right to store.
It would only work inside a Google Workspace **Shared Drive**, where the
drive owns the files rather than the uploader. That is a paid feature.

With OAuth2 the candidate owns the files, on his own 15 GB.

## 1. Create the OAuth2 client

1. https://console.cloud.google.com/ → your project
2. APIs & Services → Library → enable **Google Drive API**
3. APIs & Services → Credentials → Create Credentials → **OAuth client ID**
4. Application type: **Desktop app**
5. Download the JSON and save it as `config/oauth2_client_secret.json`
   (gitignored: it must never be committed)

## 2. Authorise

```bash
python config/setup_oauth2.py
```

It prints a URL. Open it, sign in as the account that should own the files,
accept the "Google hasn't verified this app" warning (the app is yours), and
authorise. The browser then fails to load `http://localhost/?code=4/...` --
that is expected, there is no server there. Copy the `code=` value from the
address bar and paste it back into the script.

It writes `config/gdrive_refresh_token.json` and prints the base64 blob for
the `GDRIVE_REFRESH_TOKEN_B64` GitHub secret.

## 3. Scope: `drive.file`, deliberately

The refresh token lives in a GitHub secret, so the question is what a leak
costs. Under the full `drive` scope it is the entire personal Drive; under
`drive.file` it is the job PDFs he already sends to recruiters.

That choice has one consequence worth knowing before it confuses you: **a
folder you create by hand in the browser is invisible to the app**. Only what
the app itself created is visible. So `_resolve_root_folder()` probes
`GDRIVE_PARENT_FOLDER_ID` for reachability and, if it cannot see it, finds or
creates its own `Job Hunt Pipeline` root instead. If you point that variable
at a hand-made folder you will see it fall back, and that is correct
behaviour, not a bug.

## Never revoke an old token to "tidy up"

Revoking any token for this client revokes **all** of them, including the one
currently in use -- Google revokes the whole user+client grant, not the
individual token. Doing exactly that broke the pipeline on 2026-08-23:

```json
{"error": "invalid_grant",
 "error_description": "Token has been expired or revoked."}
```

Let old tokens expire on their own. If you do need to start over, re-run
`setup_oauth2.py` and update the secret afterwards.

## Secrets used

| Secret | Required | Purpose |
|---|---|---|
| `GDRIVE_REFRESH_TOKEN_B64` | yes | OAuth2 token, base64 of `gdrive_refresh_token.json` |
| `GDRIVE_PARENT_FOLDER_ID` | optional | Root folder id; falls back to find-or-create by name |

`GDRIVE_CREDENTIALS_JSON_B64` (the Service Account key) was deleted on
2026-08-23. It was corrupt, and it could not have worked regardless.
