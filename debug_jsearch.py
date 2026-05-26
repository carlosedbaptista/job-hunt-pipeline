#!/usr/bin/env python3
"""
Debug script para JSearch API — testa a conexao e mostra a resposta completa.
"""

import os
import json
import httpx

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

print("=" * 70)
print("🔍 JSEARCH DEBUG")
print("=" * 70)
print(f"RAPIDAPI_KEY presente: {'SIM' if RAPIDAPI_KEY else 'NAO'}")
print(f"RAPIDAPI_KEY tamanho: {len(RAPIDAPI_KEY)} chars")
print(f"RAPIDAPI_KEY primeiros 10 chars: {RAPIDAPI_KEY[:10]}...")
print()

if not RAPIDAPI_KEY:
    print("❌ RAPIDAPI_KEY nao encontrada nas variaveis de ambiente!")
    print("   Adicione no .env ou exporte no shell.")
    exit(1)

url = "https://jsearch.p.rapidapi.com/search"
headers = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
}

# Teste 1: Query simples sem filtros restritivos
queries = [
    {"query": "Data Analyst Zurich", "page": "1", "num_pages": "1"},
    {"query": "Data Analyst in Zurich, Switzerland", "page": "1", "num_pages": "1", "date_posted": "week", "employment_types": "FULLTIME,INTERN"},
    {"query": "Data Analyst", "page": "1", "num_pages": "1"},
]

for i, params in enumerate(queries, 1):
    print(f"--- TESTE {i}: {params['query']} ---")
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)
        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        data = response.json()
        print(f"JSON keys: {list(data.keys())}")
        
        if "data" in data:
            jobs = data["data"]
            print(f"Jobs encontrados: {len(jobs)}")
            if jobs:
                for j in jobs[:3]:
                    print(f"  • {j.get('employer_name', 'N/A')} — {j.get('job_title', 'N/A')} ({j.get('job_city', 'N/A')})")
            else:
                print("  (lista vazia)")
        elif "message" in data:
            print(f"Mensagem de erro: {data['message']}")
        else:
            print(f"Resposta inesperada: {json.dumps(data, indent=2)[:1000]}")
            
    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code}")
        print(f"Body: {e.response.text[:1000]}")
    except Exception as e:
        print(f"Erro: {e}")
    print()

print("✅ Debug completo")
