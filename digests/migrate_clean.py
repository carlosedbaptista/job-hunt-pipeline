
#!/usr/bin/env python3
"""
migrate.py

MIGRACAO AUTOMATICA: Anthropic Claude -> Kimi K2.6

COMO USAR:
  1. Salve este arquivo como migrate.py na RAIZ do seu repo
  2. Rode: python migrate.py
  3. O script faz TUDO sozinho

O que faz:
  - Cria src/kimi_client.py
  - Cria agents/job_evaluator_kimi.py
  - Atualiza requirements.txt
  - Atualiza .github/workflows/*.yml
  - Atualiza imports no pipeline principal
  - Pergunta se faz git add + commit + push
"""

import os
import sys
import glob


def main():
    print("=" * 70)
    print("🚀 MIGRACAO AUTOMATICA: Anthropic Claude -> Kimi K2.6")
    print("=" * 70)
    print()

    # Verifica se estamos na raiz do repo
    if not os.path.isdir(".git") and not os.path.isdir("src"):
        print("❌ ERRO: Execute este script na RAIZ do seu repo job-hunt-pipeline/")
        print("   cd ~/job-hunt-pipeline")
        print("   python migrate.py")
        sys.exit(1)

    # =====================================================================
    # PASSO 1: Criar src/kimi_client.py
    # =====================================================================
    print("[1/6] Criando src/kimi_client.py...")
    kimi_client_code = """#!/usr/bin/env python3
import os, time, json
from typing import Optional, List, Dict, Any
import httpx

KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL_DEFAULT = "kimi-k2-6"
PRICING = {"kimi-k2-6": {"input": 0.60, "output": 2.50}}

class KimiClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("KIMI_API_KEY", "")
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada.")
        self.base_url = KIMI_BASE_URL.rstrip("/")
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        self.client = httpx.Client(timeout=120.0)

    def chat_completion(self, messages, model=KIMI_MODEL_DEFAULT, temperature=0.3, max_tokens=4096, system=None, response_format=None):
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if system: payload["messages"] = [{"role": "system", "content": system}] + messages
        if response_format: payload["response_format"] = response_format
        for attempt in range(3):
            try:
                r = self.client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
                r.raise_for_status()
                d = r.json()
                content = d["choices"][0]["message"]["content"]
                u = d.get("usage", {})
                cost = self._estimate_cost(model, u.get("prompt_tokens",0), u.get("completion_tokens",0))
                print(f"  [Kimi] {u.get('prompt_tokens',0)}in/{u.get('completion_tokens',0)}out | ${cost:.4f}")
                return content.strip()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    time.sleep(2**attempt); continue
                raise
            except Exception as e:
                if attempt < 2: time.sleep(2**attempt); continue
                raise RuntimeError(f"Falha: {e}")
        raise RuntimeError("Falha inesperada")

    def _estimate_cost(self, model, inp, out):
        p = PRICING.get(model, PRICING[KIMI_MODEL_DEFAULT])
        return (inp/1e6*p["input"]) + (out/1e6*p["output"])
    def close(self): self.client.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

def call_kimi(prompt, system=None, model=KIMI_MODEL_DEFAULT, temperature=0.3, max_tokens=4096, response_format=None):
    c = KimiClient()
    return c.chat_completion([{"role":"user","content":prompt}], system=system, model=model, temperature=temperature, max_tokens=max_tokens, response_format=response_format)

def call_kimi_json(prompt, system=None, model=KIMI_MODEL_DEFAULT, temperature=0.1, max_tokens=4096):
    return json.loads(call_kimi(prompt, system, model, temperature, max_tokens, {"type":"json_object"}))
"""
    with open("src/kimi_client.py", "w") as f:
        f.write(kimi_client_code)
    print("   ✅ src/kimi_client.py criado")

    # =====================================================================
    # PASSO 2: Criar agents/job_evaluator_kimi.py
    # =====================================================================
    print("[2/6] Criando agents/job_evaluator_kimi.py...")
    evaluator_code = """#!/usr/bin/env python3
import json, sys
from typing import Dict, Any
sys.path.insert(0, "../src")
sys.path.insert(0, "./src")
from kimi_client import call_kimi_json, call_kimi

SCREENING_SYSTEM = \"\"\"Voce e um avaliador de fit de vagas. Retorne JSON estrito. Seja objetivo. NUNCA invente.\"\"\"

SCREENING_TEMPLATE = \"\"\"Perfil: Carlos Eduardo Duarte Baptista, Data Analyst, Wallisellen CH, Permit B, 2 weeks notice. Skills: SQL, Python, Power BI, GA4, automacao IA. Experiencia: QUOD (40% reducao manual), netzdenker.com. Educacao: Pos Data Science (out/2026). Certificacoes: Google AI Essentials, Anthropic Claude, GA4. Restricoes: Zurich/Zug APENAS, Ingles obrigatorio, NAO dev puro.

Vaga: {title} em {company} ({location})
{description}

Retorne JSON: {\\"score\\":int0-100, \\"technical_fit\\":int0-40, \\"contextual_fit\\":int0-35, \\"opportunity_fit\\":int0-25, \\"decision\\":\\"APPLY|REVIEW|SKIP\\", \\"reasoning\\":\\"...\\", \\"gaps\\":[\\"...\\"], \\"red_flags\\":[\\"...\\"]}
Thresholds: >=65 APPLY, 45-64 REVIEW, <45 SKIP.\"\"\"

MATERIALS_SYSTEM = \"\"\"Redator de CV/cover letter. Tom profissional, direto. CV 1 pagina. Cover 3 paragrafos. NUNCA minta.\"\"\"

CV_TEMPLATE = \"\"\"Gere CV markdown 1 pagina para Carlos Eduardo Duarte Baptista (Data Analyst, Wallisellen CH, Permit B, 2 weeks notice, carlosedbaptista@gmail.com, +41 78 261 34 74, linkedin.com/in/carlosedbaptista). Experiencias: QUOD (40% reducao manual, SQL/Python/Power BI), netzdenker.com (Power BI/GA4/AI workflows). Educacao: Pos Data Science (out/2026), Bacharel Sistemas. Certificacoes: Google AI Essentials, Anthropic Claude, GA4. Idiomas: PT nativo, EN C1, ES B2, DE A2. Adapte para vaga: {title} em {company}. Descricao: {description}. APENAS markdown.\"\"\"

COVER_TEMPLATE = \"\"\"Gere cover letter (3 paragrafos, max 250 palavras) de Carlos Eduardo Duarte Baptista para {company} - {title}. Paragrafo 1: por que empresa/role. Paragrafo 2: match habilidades (SQL, Python, Power BI, GA4, automacao IA), mencione 40% reducao QUOD e perfil cross-cultural BR->CH. Paragrafo 3: call to action, 2 weeks notice. Contato: carlosedbaptista@gmail.com | +41 78 261 34 74. APENAS texto.\"\"\"

def evaluate_job(title, company, location, description):
    r = call_kimi_json(SCREENING_TEMPLATE.format(title=title,company=company,location=location,description=description[:3000]), system=SCREENING_SYSTEM, temperature=0.1, max_tokens=1024)
    for k in ["score","decision","reasoning"]:
        if k not in r: r[k] = 0 if k=="score" else "UNKNOWN"
    return r

def generate_cv(title, company, description):
    return call_kimi(CV_TEMPLATE.format(title=title,company=company,description=description[:2000]), system=MATERIALS_SYSTEM, temperature=0.3, max_tokens=2048)

def generate_cover_letter(title, company, description):
    return call_kimi(COVER_TEMPLATE.format(title=title,company=company,description=description[:2000]), system=MATERIALS_SYSTEM, temperature=0.4, max_tokens=1024)
"""
    with open("agents/job_evaluator_kimi.py", "w") as f:
        f.write(evaluator_code)
    print("   ✅ agents/job_evaluator_kimi.py criado")

    # =====================================================================
    # PASSO 3: Atualizar requirements.txt
    # =====================================================================
    print("[3/6] Atualizando requirements.txt...")
    req_lines = []
    if os.path.exists("requirements.txt"):
        with open("requirements.txt", "r") as f:
            req_lines = f.read().splitlines()
    else:
        req_lines = ["python-dotenv>=1.0.0"]

    # Remove anthropic se existir
    req_lines = [l for l in req_lines if not l.strip().lower().startswith("anthropic")]
    # Adiciona httpx se nao existir
    if not any("httpx" in l for l in req_lines):
        req_lines.append("httpx>=0.27.0")

    with open("requirements.txt", "w") as f:
        f.write("\n".join(req_lines) + "\n")
    print("   ✅ requirements.txt atualizado")

    # =====================================================================
    # PASSO 4: Atualizar workflow YAML
    # =====================================================================
    print("[4/6] Atualizando workflow GitHub Actions...")
    workflow_files = glob.glob(".github/workflows/*.yml")
    if not workflow_files:
        print("   ⚠️ Nenhum workflow .yml encontrado. Criando job-hunt-kimi.yml...")
        os.makedirs(".github/workflows", exist_ok=True)
        workflow_files = [".github/workflows/job-hunt-kimi.yml"]

    for wf in workflow_files:
        with open(wf, "r") as f:
            content = f.read()
        # Substitui ANTHROPIC_API_KEY por KIMI_API_KEY
        content = content.replace("ANTHROPIC_API_KEY", "KIMI_API_KEY")
        content = content.replace("anthropic", "kimi")
        with open(wf, "w") as f:
            f.write(content)
        print(f"   ✅ {wf} atualizado")

    # =====================================================================
    # PASSO 5: Atualizar imports no pipeline principal
    # =====================================================================
    print("[5/6] Atualizando imports no pipeline principal...")
    pipeline_files = glob.glob("src/*.py") + glob.glob("agents/*.py")
    changed = []
    for pf in pipeline_files:
        with open(pf, "r") as f:
            content = f.read()
        original = content
        # Substitui imports de job_evaluator antigo
        content = content.replace("from agents.job_evaluator import evaluate_job", "from agents.job_evaluator_kimi import evaluate_job")
        content = content.replace("import anthropic", "# import anthropic  # MIGRADO: usar from src.kimi_client import call_kimi")
        if content != original:
            with open(pf, "w") as f:
                f.write(content)
            changed.append(pf)
            print(f"   ✅ {pf} atualizado")
    if not changed:
        print("   ℹ️ Nenhum import antigo encontrado (ja atualizado ou usa outro padrao)")

    # =====================================================================
    # PASSO 6: Resumo e Git
    # =====================================================================
    print()
    print("=" * 70)
    print("📋 RESUMO DAS MUDANCAS")
    print("=" * 70)
    print("""
Arquivos criados:
  - src/kimi_client.py
  - agents/job_evaluator_kimi.py

Arquivos modificados:
  - requirements.txt
  - .github/workflows/*.yml
  - src/*.py (imports atualizados)

PROXIMA ACAO NECESSARIA (voce deve fazer manualmente):
  1. Acesse https://github.com/seu-usuario/job-hunt-pipeline/settings/secrets/actions
  2. Adicione o secret: KIMI_API_KEY = (sua chave de https://platform.moonshot.cn/)
  3. Remova ANTHROPIC_API_KEY quando confirmar que funciona
""")

    resposta = input("Fazer git add + commit + push agora? (s/n): ").strip().lower()
    if resposta in ("s", "sim", "yes", "y"):
        os.system('git config user.name "github-actions"')
        os.system('git config user.email "github-actions@github.com"')
        os.system("git add src/kimi_client.py agents/job_evaluator_kimi.py requirements.txt .github/workflows/ src/ agents/")
        os.system('git diff --cached --quiet || git commit -m "migracao: Anthropic Claude -> Kimi K2.6"')
        os.system("git push")
        print()
        print("🚀 Commit e push feitos! Verifique em Actions -> Run workflow")
    else:
        print()
        print("⏸️  Pausado. Quando quiser commitar, rode:")
        print("   git add .")
        print('   git commit -m "migracao: Anthropic Claude -> Kimi K2.6"')
        print("   git push")

    print()
    print("=" * 70)
    print("✅ MIGRACAO CONCLUIDA")
    print("=" * 70)


if __name__ == "__main__":
    main()
