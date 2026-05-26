#!/usr/bin/env python3
import json, sys
from typing import Dict, Any
sys.path.insert(0, "../src")
sys.path.insert(0, "./src")
from kimi_client import call_kimi_json, call_kimi

SCREENING_SYSTEM = """Voce e um avaliador de fit de vagas. Retorne JSON estrito. Seja objetivo. NUNCA invente."""

SCREENING_TEMPLATE = """Perfil: Carlos Eduardo Duarte Baptista, Data Analyst, Wallisellen CH, Permit B, 2 weeks notice. Skills: SQL, Python, Power BI, GA4, automacao IA. Experiencia: QUOD (40% reducao manual), netzdenker.com. Educacao: Pos Data Science (out/2026). Certificacoes: Google AI Essentials, Anthropic Claude, GA4. Restricoes: Zurich/Zug APENAS, Ingles obrigatorio, NAO dev puro.

Vaga: {title} em {company} ({location})
{description}

Retorne JSON: {\"score\":int0-100, \"technical_fit\":int0-40, \"contextual_fit\":int0-35, \"opportunity_fit\":int0-25, \"decision\":\"APPLY|REVIEW|SKIP\", \"reasoning\":\"...\", \"gaps\":[\"...\"], \"red_flags\":[\"...\"]}
Thresholds: >=65 APPLY, 45-64 REVIEW, <45 SKIP."""

MATERIALS_SYSTEM = """Redator de CV/cover letter. Tom profissional, direto. CV 1 pagina. Cover 3 paragrafos. NUNCA minta."""

CV_TEMPLATE = """Gere CV markdown 1 pagina para Carlos Eduardo Duarte Baptista (Data Analyst, Wallisellen CH, Permit B, 2 weeks notice, carlosedbaptista@gmail.com, +41 78 261 34 74, linkedin.com/in/carlosedbaptista). Experiencias: QUOD (40% reducao manual, SQL/Python/Power BI), netzdenker.com (Power BI/GA4/AI workflows). Educacao: Pos Data Science (out/2026), Bacharel Sistemas. Certificacoes: Google AI Essentials, Anthropic Claude, GA4. Idiomas: PT nativo, EN C1, ES B2, DE A2. Adapte para vaga: {title} em {company}. Descricao: {description}. APENAS markdown."""

COVER_TEMPLATE = """Gere cover letter (3 paragrafos, max 250 palavras) de Carlos Eduardo Duarte Baptista para {company} - {title}. Paragrafo 1: por que empresa/role. Paragrafo 2: match habilidades (SQL, Python, Power BI, GA4, automacao IA), mencione 40% reducao QUOD e perfil cross-cultural BR->CH. Paragrafo 3: call to action, 2 weeks notice. Contato: carlosedbaptista@gmail.com | +41 78 261 34 74. APENAS texto."""

def evaluate_job(title, company, location, description):
    r = call_kimi_json(SCREENING_TEMPLATE.format(title=title,company=company,location=location,description=description[:3000]), system=SCREENING_SYSTEM, temperature=0.1, max_tokens=1024)
    for k in ["score","decision","reasoning"]:
        if k not in r: r[k] = 0 if k=="score" else "UNKNOWN"
    return r

def generate_cv(title, company, description):
    return call_kimi(CV_TEMPLATE.format(title=title,company=company,description=description[:2000]), system=MATERIALS_SYSTEM, temperature=0.3, max_tokens=2048)

def generate_cover_letter(title, company, description):
    return call_kimi(COVER_TEMPLATE.format(title=title,company=company,description=description[:2000]), system=MATERIALS_SYSTEM, temperature=0.4, max_tokens=1024)
