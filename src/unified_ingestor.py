#!/usr/bin/env python3
"""
unified_ingestor.py

Orquestra ingestao de MULTIPLAS fontes:
  1. JSearch API (busca ativa)
  2. Gmail (alertas por email)
  3. Deduplica entre fontes
  4. Salva em data/raw_jobs/all_jobs_{data}.json

Uso:
  python src/unified_ingestor.py
"""

import os
import sys
import json
import glob
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, "agents")
sys.path.insert(0, "./agents")


def load_jsearch_jobs() -> List[Dict[str, Any]]:
    files = sorted(glob.glob("data/raw_jobs/jsearch_*.json"))
    if not files:
        print("  ℹ️  Nenhum arquivo JSearch.")
        return []
    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"  ✅ JSearch: {len(jobs)} vagas de {latest}")
    return jobs


def load_email_jobs() -> List[Dict[str, Any]]:
    """Carrega vagas parseadas de emails (gerado por agents/email_parser.py)."""
    filepath = "digests/parsed_jobs_latest.json"
    if not os.path.exists(filepath):
        print("  ℹ️  Nenhum arquivo de email parseado.")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"  ✅ Email: {len(jobs)} vagas de {filepath}")
    return jobs


def normalize_to_legacy(job: Dict[str, Any]) -> Dict[str, Any]:
    """Converte campos do formato novo (JSearch) para o formato legado do pipeline."""
    return {
        "empresa": job.get("company") or job.get("empresa", "Unknown"),
        "titulo": job.get("title") or job.get("titulo", "Unknown"),
        "localizacao": job.get("location") or job.get("localizacao", "Unknown"),
        "descricao": job.get("description") or job.get("descricao", ""),
        "url": job.get("url", ""),
        "portal": job.get("portal", "unknown"),
        "idioma": job.get("idioma", "en"),
        "data_post": job.get("posted_at") or job.get("data_post", datetime.now().isoformat()),
    }


def deduplicate_all(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for job in jobs:
        key = (
            job.get("company", job.get("empresa", "")).lower().strip(),
            job.get("title", job.get("titulo", "")).lower().strip(),
            job.get("location", job.get("localizacao", "")).lower().strip(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def save_unified(jobs: List[Dict[str, Any]]) -> str:
    os.makedirs("data/raw_jobs", exist_ok=True)
    filepath = f"data/raw_jobs/all_jobs_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    print(f"  💾 {len(jobs)} vagas unificadas → {filepath}")
    return filepath


def save_legacy_format(jobs: List[Dict[str, Any]]) -> str:
    """Salva no formato que o pipeline antigo (evaluator, digest, etc.) espera."""
    os.makedirs("digests", exist_ok=True)
    filepath = "digests/new_jobs_latest.json"
    legacy_jobs = [normalize_to_legacy(j) for j in jobs]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(legacy_jobs, f, ensure_ascii=False, indent=2)
    print(f"  💾 {len(legacy_jobs)} vagas (formato legado) → {filepath}")
    return filepath


def main():
    print("=" * 70)
    print("🔗 UNIFIED INGESTOR — JSearch + Email")
    print("=" * 70)

    jsearch_jobs = load_jsearch_jobs()
    email_jobs = load_email_jobs()

    all_jobs = jsearch_jobs + email_jobs
    if not all_jobs:
        print("\n⚠️  Nenhuma vaga de nenhuma fonte.")
        return None

    unique = deduplicate_all(all_jobs)
    print(f"\n📊 Total: {len(all_jobs)} | Após dedup: {len(unique)}")

    save_unified(unique)
    filepath = save_legacy_format(unique)
    return filepath


if __name__ == "__main__":
    main()
