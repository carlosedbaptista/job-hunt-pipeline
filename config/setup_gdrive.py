#!/usr/bin/env python3
"""
Helper script for Google Drive setup.
Converts Service Account JSON to base64 and tests connection.
"""
import os
import sys
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def json_to_b64(filepath):
    """Converte arquivo JSON para base64 (para GitHub Secret)."""
    with open(filepath, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    print("\n=== BASE64 DO JSON (copie e cole no GitHub Secret) ===")
    print(b64)
    print("\n=== FIM ===")
    print(f"Tamanho: {len(b64)} caracteres")
    return b64


def test_drive():
    """Testa conexao com Google Drive."""
    from gdrive_uploader import test_connection, upload_cv_cl
    print("\n[Testando conexao com Google Drive...]")
    ok = test_connection()
    if ok:
        print("✅ Conexao OK! O upload funcionara no pipeline.")
    else:
        print("❌ Falha na conexao. Verifique suas credenciais.")
    return ok


if __name__ == "__main__":
    print("=== Google Drive Setup Helper ===\n")
    print("Opcoes:")
    print("  1. Converter JSON para base64 (para GitHub Secret)")
    print("  2. Testar conexao com Google Drive")
    print("  3. Ambos (converter + testar)\n")

    choice = input("Escolha (1/2/3): ").strip()

    if choice in ("1", "3"):
        path = input("Caminho do arquivo JSON da Service Account: ").strip().strip('"')
        if os.path.exists(path):
            json_to_b64(path)
            # Salva localmente tambem
            dst = os.path.join(os.path.dirname(__file__), "gdrive_credentials.json")
            import shutil
            shutil.copy2(path, dst)
            print(f"\nJSON tambem copiado para: {dst}")
        else:
            print(f"Arquivo nao encontrado: {path}")
            sys.exit(1)

    if choice in ("2", "3"):
        test_drive()
