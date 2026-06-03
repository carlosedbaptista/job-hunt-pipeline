#!/usr/bin/env python3
"""
Gera o refresh token OAuth2 para upload no Google Drive pessoal.
Rode uma vez localmente para autorizar o app.
"""
import os
import sys
import json
import urllib.parse
import urllib.request
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

SCOPES = ["https://www.googleapis.com/auth/drive"]
REDIRECT_URI = "http://localhost"


def load_client_secrets():
    """Carrega client_id e client_secret do JSON de credenciais OAuth2."""
    path = os.path.join(os.path.dirname(__file__), "oauth2_client_secret.json")
    if not os.path.exists(path):
        print(f"ERRO: {path} nao encontrado.")
        print("Baixe o JSON OAuth2 (Desktop app) do Google Cloud Console e salve aqui.")
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    installed = data.get("installed", data.get("web", {}))
    return installed.get("client_id"), installed.get("client_secret"), installed.get("token_uri", "https://oauth2.googleapis.com/token")


def generate_auth_url(client_id):
    """Gera URL para o usuario autorizar o app."""
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
    """Troca o authorization code por access + refresh tokens."""
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
        print(f"Erro ao trocar code: {e.read().decode()}")
        return None


def main():
    print("=== Google Drive OAuth2 Setup ===\n")

    creds = load_client_secrets()
    if not creds:
        return
    client_id, client_secret, token_uri = creds

    auth_url = generate_auth_url(client_id)

    print("1. Abra esta URL no seu navegador:")
    print(f"\n   {auth_url}\n")
    print("2. Faca login com sua conta Google e autorize o app.")
    print("3. Voce sera redirecionado para localhost (provavelmente dara erro no navegador).")
    print("4. Copie o 'code' da URL de redirecionamento (ex: http://localhost/?code=4/abc...).")
    print("   Dica: o code comeca com '4/' e termina antes de '&scope'\n")

    code = input("Cole o authorization code aqui: ").strip()
    if not code:
        print("Code vazio. Abortando.")
        return

    print("\nTrocando code por tokens...")
    tokens = exchange_code_for_tokens(client_id, client_secret, token_uri, code)
    if not tokens:
        print("Falha ao obter tokens.")
        return

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("ATENCAO: Nao recebemos refresh_token.")
        print("Isso acontece se voce ja autorizou este app antes.")
        print("Tente revogar o acesso em https://myaccount.google.com/permissions e tente novamente.")
        return

    # Salva refresh token
    out_path = os.path.join(os.path.dirname(__file__), "gdrive_refresh_token.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": token_uri,
        }, f, indent=2)

    print(f"\n✅ Refresh token salvo em: {out_path}")
    print("O pipeline agora pode fazer upload no seu Drive pessoal!")

    # Tambem gera base64 para GitHub Secret
    with open(out_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    print(f"\n=== BASE64 PARA GITHUB SECRET (GDRIVE_REFRESH_TOKEN_B64) ===")
    print(b64)
    print("=== FIM ===")


if __name__ == "__main__":
    main()
