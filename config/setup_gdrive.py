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
    """Converts a JSON file to base64 (for a GitHub Secret)."""
    with open(filepath, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    print("\n=== BASE64 OF THE JSON (copy and paste into the GitHub Secret) ===")
    print(b64)
    print("\n=== END ===")
    print(f"Size: {len(b64)} characters")
    return b64


def test_drive():
    """Tests the Google Drive connection."""
    from gdrive_uploader import test_connection, upload_cv_cl
    print("\n[Testing Google Drive connection...]")
    ok = test_connection()
    if ok:
        print("OK: Connection successful! Upload will work in the pipeline.")
    else:
        print("ERROR: Connection failed. Check your credentials.")
    return ok


if __name__ == "__main__":
    print("=== Google Drive Setup Helper ===\n")
    print("Options:")
    print("  1. Convert JSON to base64 (for a GitHub Secret)")
    print("  2. Test the Google Drive connection")
    print("  3. Both (convert + test)\n")

    choice = input("Choose (1/2/3): ").strip()

    if choice in ("1", "3"):
        path = input("Path to the Service Account JSON file: ").strip().strip('"')
        if os.path.exists(path):
            json_to_b64(path)
            # Also save a local copy
            dst = os.path.join(os.path.dirname(__file__), "gdrive_credentials.json")
            import shutil
            shutil.copy2(path, dst)
            print(f"\nJSON also copied to: {dst}")
        else:
            print(f"File not found: {path}")
            sys.exit(1)

    if choice in ("2", "3"):
        test_drive()
