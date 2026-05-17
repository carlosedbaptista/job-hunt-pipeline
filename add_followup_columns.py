#!/usr/bin/env python3
"""
add_followup_columns.py

Adiciona as 3 colunas novas ao banco de dados existente:
- recruiter_email
- last_followup_date
- followup_count
"""

import sqlite3

DB_PATH = "tracker/jobs.db"

def add_followup_columns():
    """Adiciona colunas pra follow-up ao banco existente."""
    
    print("\n" + "="*70)
    print("📊 Adicionando colunas de follow-up ao banco de dados")
    print("="*70 + "\n")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Pega columns atuais
    cursor.execute("PRAGMA table_info(applications)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    
    print(f"Colunas existentes: {existing_columns}\n")
    
    columns_to_add = [
        ("recruiter_email", "TEXT"),
        ("last_followup_date", "TIMESTAMP"),
        ("followup_count", "INTEGER DEFAULT 0"),
    ]
    
    for col_name, col_type in columns_to_add:
        if col_name in existing_columns:
            print(f"✅ {col_name} já existe, pulando...")
        else:
            print(f"➕ Adicionando {col_name}...")
            try:
                cursor.execute(f"ALTER TABLE applications ADD COLUMN {col_name} {col_type}")
                print(f"   ✅ Sucesso!\n")
            except Exception as e:
                print(f"   ❌ Erro: {e}\n")
    
    conn.commit()
    conn.close()
    
    print("="*70)
    print("✅ Banco atualizado!")
    print("="*70 + "\n")

if __name__ == "__main__":
    add_followup_columns()
