#!/usr/bin/env python3
"""
=== FASE 1: LIMPEZA IMEDIATA ===
Remove artefatos mortos, move scripts para pasta correta, atualiza .gitignore.
"""
import os
import shutil
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERRO: Rode dentro da pasta do repo"); exit(1)

print("=== FASE 1: LIMPEZA IMEDIATA ===\n")

# 1. Criar pastas necessarias
for d in ["scripts", "docs/legacy", "config", "data/history"]:
    os.makedirs(os.path.join(REPO, d), exist_ok=True)
print("[OK] Pastas criadas: scripts/, docs/legacy/, config/, data/history/")

# 2. Remover fix_*.py e hotfix_*.py da raiz
removed = []
for f in os.listdir(REPO):
    if f.startswith("fix_") and f.endswith(".py"):
        os.remove(os.path.join(REPO, f))
        removed.append(f)
    elif f.startswith("hotfix_") and f.endswith(".py"):
        os.remove(os.path.join(REPO, f))
        removed.append(f)
if removed:
    print(f"[OK] Removidos {len(removed)} arquivos de fix: {', '.join(removed)}")
else:
    print("[OK] Nenhum arquivo de fix encontrado na raiz")

# 3. Remover package.json e setup-gmail.js
for f in ["package.json", "setup-gmail.js"]:
    fp = os.path.join(REPO, f)
    if os.path.exists(fp):
        os.remove(fp)
        print(f"[OK] Removido: {f}")
    else:
        print(f"[OK] Ja nao existe: {f}")

# 4. Mover scripts de debug para scripts/
for f in ["debug_jsearch.py", "add_followup_columns.py"]:
    src = os.path.join(REPO, f)
    dst = os.path.join(REPO, "scripts", f)
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"[OK] Movido: {f} -> scripts/")
    else:
        print(f"[OK] Ja nao existe na raiz: {f}")

# 5. Mover .md desatualizados para docs/legacy/
legacy_docs = ["GUIDE.md", "FOLLOWUPS.md", "ANALYTICS.md"]
for f in legacy_docs:
    src = os.path.join(REPO, f)
    dst = os.path.join(REPO, "docs/legacy", f)
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"[OK] Movido: {f} -> docs/legacy/")
    else:
        print(f"[OK] Ja nao existe na raiz: {f}")

# 6. Atualizar .gitignore
gitignore_path = os.path.join(REPO, ".gitignore")
if os.path.exists(gitignore_path):
    with open(gitignore_path, "r") as f:
        content = f.read()
    additions = """
# Scripts e artefatos temporarios
scripts/
docs/legacy/
fix_*.py
hotfix_*.py
debug_*.py

# Fix scripts na raiz (nao commitar)
/*fix*.py
/*hotfix*.py
"""
    if "scripts/" not in content:
        with open(gitignore_path, "a") as f:
            f.write(additions)
        print("[OK] .gitignore atualizado")
    else:
        print("[OK] .gitignore ja contem regras")

# 7. Stage e commit
run("git add -A")
ok, out, err = run('git commit -m "chore: cleanup dead artifacts, move legacy docs to docs/legacy/"')
if ok:
    print("\n[OK] Commit feito com sucesso!")
    print("     Proximo passo: git push origin main")
else:
    print(f"\n[!] Commit falhou (pode ser nada para commitar): {err[:200]}")

print("\n=== FASE 1 CONCLUIDA ===")
print("Artefatos removidos, pastas organizadas, .gitignore atualizado.")
print("Execute 'git push origin main' para enviar as mudancas.")
