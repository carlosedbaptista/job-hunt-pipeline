#!/usr/bin/env python3
"""
refactor_thresholds.py

Script pra atualizar TODOS os thresholds de scoring no pipeline
De: 75+ APPLY, 55-74 REVIEW, <55 UNCERTAIN
Para: 65+ APPLY, 45-64 REVIEW, <45 UNCERTAIN

Roda em todos os arquivos Python do projeto.
"""

import os
import re
from pathlib import Path

# Mapeamento de mudanças (old -> new)
REPLACEMENTS = [
    # Thresholds numéricos
    (r">= 75", ">= 65"),
    (r"<= 75", "<= 65"),
    (r">75", ">65"),
    (r"75\)", "65)"),
    (r"55 <=", "45 <="),
    (r">= 55", ">= 45"),
    (r"< 55", "< 45"),
    (r"55 <", "45 <"),
    (r"\[55 ", "[45 "),
    (r", 55\]", ", 45]"),
    (r"\(55,", "(45,"),
    (r"55,", "45,"),
    
    # Mensagens e comentários
    (r"score >= 75", "score >= 65"),
    (r"score >= 55", "score >= 45"),
    (r"score < 55", "score < 45"),
    (r"score < 75", "score < 65"),
    (r"Score >= 75", "Score >= 65"),
    (r"Score >= 55", "Score >= 45"),
    (r"Score < 55", "Score < 45"),
    (r"Score >= 75", "Score >= 65"),
    (r"Score 55-74", "Score 45-64"),
    (r"Nenhuma vaga com score >= 75", "Nenhuma vaga com score >= 65"),
    (r"Nenhuma vaga com score >= 75", "Nenhuma vaga com score >= 65"),
    
    # APPLY/REVIEW/UNCERTAIN descriptions
    (r"Score >= 75: APPLY", "Score >= 65: APPLY"),
    (r"Score 55-74: REVIEW", "Score 45-64: REVIEW"),
    (r"Score < 55: UNCERTAIN", "Score < 45: UNCERTAIN"),
    
    # Ranges em strings
    (r"55-74", "45-64"),
    (r"75\+", "65+"),
]

# Arquivos para processar
TARGET_FILES = [
    "agents/job_evaluator.py",
    "agents/email_notifier.py",
    "agents/cover_letter_writer.py",
    "agents/cv_tailor.py",
    "agents/digest_generator.py",
    "src/week3_pipeline.py",
    "src/week4_pipeline.py",
    "evaluation_rubric.md",
    "GUIDE.md",
    "SEMANA_9_ANALYTICS.md",
]

def process_file(filepath: str) -> tuple[int, list[str]]:
    """
    Processa um arquivo e aplica todas as substituições.
    Retorna: (número de mudanças, lista de mudanças realizadas)
    """
    if not os.path.exists(filepath):
        return 0, [f"⚠️  Arquivo não encontrado: {filepath}"]
    
    with open(filepath, "r", encoding="utf-8") as f:
        original_content = f.read()
    
    content = original_content
    changes_made = []
    
    for old_pattern, new_pattern in REPLACEMENTS:
        # Usa regex pra substituir
        new_content = re.sub(old_pattern, new_pattern, content)
        
        if new_content != content:
            # Conta quantas mudanças
            count = len(re.findall(old_pattern, content))
            if count > 0:
                changes_made.append(f"  • {old_pattern:30} → {new_pattern:30} ({count}x)")
            content = new_content
    
    # Se houve mudanças, salva o arquivo
    if content != original_content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return len(changes_made), changes_made
    
    return 0, []


def main():
    print("\n" + "="*80)
    print("🔄 REFACTOR: Atualizar Thresholds 75→65 e 55→45")
    print("="*80 + "\n")
    
    total_changes = 0
    files_modified = 0
    
    for filepath in TARGET_FILES:
        full_path = filepath if os.path.isabs(filepath) else os.path.join(".", filepath)
        
        num_changes, changes = process_file(full_path)
        
        if num_changes > 0:
            files_modified += 1
            total_changes += num_changes
            
            print(f"✅ {filepath}")
            for change in changes:
                print(f"   {change}")
            print()
    
    print("="*80)
    print(f"📊 RESUMO:")
    print(f"   • Arquivos modificados: {files_modified}/{len(TARGET_FILES)}")
    print(f"   • Total de mudanças: {total_changes}")
    print("="*80 + "\n")
    
    if files_modified > 0:
        print("✅ Refactor completo! Agora:\n")
        print("   1. Revise as mudanças:")
        print("      git diff")
        print()
        print("   2. Testa o pipeline:")
        print("      python agents/job_evaluator.py")
        print()
        print("   3. Faz commit:")
        print("      git add .")
        print('      git commit -m "Refactor: Update thresholds 75→65, 55→45"')
        print("      git push")
    else:
        print("⚠️  Nenhum arquivo foi modificado (já está atualizado?)")


if __name__ == "__main__":
    main()
