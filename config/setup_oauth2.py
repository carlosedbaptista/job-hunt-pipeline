#!/usr/bin/env python3
"""
Generates the OAuth2 refresh token for uploading to a personal Google Drive.
Run this once locally to authorize the app.
"""
import os
import sys
import json
import urllib.parse
import urllib.request
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Must match src/gdrive_uploader.py. drive.file limits the token to files the
# app itself created -- see the comment there for why that matters.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
REDIRECT_URI = "http://localhost"


def load_client_secrets():
    """Loads client_id and client_secret from the OAuth2 credentials JSON."""
    path = os.path.join(os.path.dirname(__file__), "oauth2_client_secret.json")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found.")
        print("Download the OAuth2 JSON (Desktop app) from the Google Cloud Console and save it here.")
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    installed = data.get("installed", data.get("web", {}))
    return installed.get("client_id"), installed.get("client_secret"), installed.get("token_uri", "https://oauth2.googleapis.com/token")


def generate_auth_url(client_id):
    """Generates the URL for the user to authorize the app."""
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "response_type": "code",
    }
    return "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)


def exchange_code_for_tokens(client_id, client_secret, token_uri, code):
    """Exchanges the authorization code for access + refresh tokens."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_uri, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Error exchanging code: {e.read().decode()}")
        return None


def main():
    print("=== Google Drive OAuth2 Setup ===\n")

    creds = load_client_secrets()
    if not creds:
        return
    client_id, client_secret, token_uri = creds

    auth_url = generate_auth_url(client_id)

    print("1. Open this URL in your browser:")
    print(f"\n   {auth_url}\n")
    print("2. Log in with your Google account and authorize the app.")
    print("3. You will be redirected to localhost (the browser will likely show an error page).")
    print("4. Copy the 'code' from the redirect URL (e.g. http://localhost/?code=4/abc...).")
    print("   Tip: the code starts with '4/' and ends before '&scope'\n")

    code = input("Paste the authorization code here: ").strip()
    if not code:
        print("Empty code. Aborting.")
        return

    print("\nExchanging code for tokens...")
    tokens = exchange_code_for_tokens(client_id, client_secret, token_uri, code)
    if not tokens:
        print("Failed to obtain tokens.")
        return

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("WARNING: No refresh_token received.")
        print("This happens if you've already authorized this app before.")
        print("Try revoking access at https://myaccount.google.com/permissions and try again.")
        return

    # Save the refresh token
    out_path = os.path.join(os.path.dirname(__file__), "gdrive_refresh_token.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": token_uri,
        }, f, indent=2)

    print(f"\nOK: Refresh token saved to: {out_path}")
    print("The pipeline can now upload to your personal Drive!")

    # Also generate base64 for the GitHub Secret
    with open(out_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    print(f"\n=== BASE64 FOR GITHUB SECRET (GDRIVE_REFRESH_TOKEN_B64) ===")
    print(b64)
    print("=== END ===")


if __name__ == "__main__":
    main()
