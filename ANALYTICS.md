# Analytics & Insights — Guia Completo

## O que você tem agora

Um **sistema de análise completo** que:
- ✅ Analisa dados das suas aplicações
- ✅ Gera insights por indústria, ATS, tipo de vaga
- ✅ Mostra taxa de resposta por categoria
- ✅ Fornece recomendações de otimização
- ✅ Visualiza dados em gráficos interativos

---

## Como Usar

### PASSO 1: Executar a análise

```bash
# Gera o relatório de analytics
python agents/analytics_engine.py

# Gera o dashboard HTML
python src/analytics_dashboard.py
```

### PASSO 2: Ver o dashboard

Abre em seu navegador:
```bash
# Windows
start digests/analytics.html

# macOS
open digests/analytics.html

# Linux
firefox digests/analytics.html
```

---

## Visualizações

O dashboard mostra:

### 1. **Métricas Gerais**
- Total de aplicações
- Total de respostas
- Taxa de resposta geral
- Tempo médio de resposta

### 2. **Taxa de Resposta por Indústria**
Qual setor tem maior sucesso?
- Tech, Finance, Pharma, Manufacturing, Retail, Consulting, Government, Other

**Use para:** Focar em indústrias com melhor resposta

### 3. **Taxa de Resposta por ATS**
Qual plataforma funciona melhor pra você?
- Workday, Greenhouse, Lever, Talentsoft, LinkedIn, Indeed, Generic, Other

**Use para:** Priorizar vagas em plataformas responsivas

### 4. **Taxa de Resposta por Tipo de Vaga**
Qual role tem melhor fit?
- Data Analyst, Business Analyst, AI/ML, Reporting, Data Engineer, Other

**Use para:** Focar em roles onde você tem melhor taxa

### 5. **Distribuição de Aplicações**
Proporção de aplicações por indústria

**Use para:** Identificar se está concentrado demais em 1 setor

---

## Recomendações Automáticas

O sistema gera 3 recomendações:

1. **🎯 Indústria com melhor fit**
   - Exemplo: "Foco em Tech: 35% de taxa de resposta"
   - Ação: Aumentar alertas de vagas em Tech

2. **🏢 Plataforma mais responsiva**
   - Exemplo: "Greenhouse tem melhor resposta (40%)"
   - Ação: Priorizar vagas no Greenhouse

3. **💼 Role com melhor taxa**
   - Exemplo: "Business Analyst tem 50% de resposta"
   - Ação: Buscar mais vagas de Business Analyst

---

## Integração no Pipeline

A análise pode rodar:

### Opção A: Manualmente (quando quiser ver insights)
```bash
python src/analytics_dashboard.py
```

### Opção B: Automaticamente a cada run
Edita `.github/workflows/job-hunt-scheduler.yml`:

```yaml
      - name: Generate Analytics
        run: |
          python agents/analytics_engine.py || true
          python src/analytics_dashboard.py || true
```

---

## Otimizando a Rubrica de Fit

Use a análise pra refinar sua rubrica:

**Exemplo Real:**
- Você pensava que Finance era bom, mas taxa de resposta é 5%
- Tech tem 35% de resposta
- **Ação:** Aumentar peso de keywords de Tech na rubrica

```python
# Em agents/job_evaluator.py, ajuste os weights:
TECHNICAL_FIT = 40  # Aumenta ênfase em Tech skills
CONTEXTUAL_FIT = 35  # Aumenta ênfase em Tech companies
```

---

## Métricas Importantes

### Taxa de Resposta
**O que é:** % de aplicações que recebem resposta
**Meta:** > 30%
**Ação se baixo:** Aumentar fit da rubrica

### Tempo Médio de Resposta
**O que é:** Dias até receber resposta
**Normal:** 5-14 dias
**Ação se alto:** Acompanhar empresas antigas

### Taxa de Rejeição
**O que é:** % de respostas que são rejeições
**Normal:** 60-70%
**Ação se alto:** Revisar rubrica de fit

---

## Próximas Análises (Advanced)

### 1. Correlação Score vs Resposta
**Hipótese:** Aplicações com score > 75 têm 2x mais resposta
**Como:** Armazenar score no banco e correlacionar

### 2. Análise de Tamanho de Empresa
**Pergunta:** Startups vs PME vs Enterprise — qual responde melhor?
**Como:** Adicionar classificação por tamanho na rubrica

### 3. A/B Testing de Cover Letters
**Pergunta:** Qual estilo de cover letter tem mais resposta?
**Como:** Variar tom e medir resultados

### 4. Análise Temporal
**Pergunta:** Qual mês/dia da semana tem mais postagens?
**Como:** Agrupar por data e encontrar padrões

---

## Checklist Final

- [ ] Rodou `python agents/analytics_engine.py`
- [ ] Rodou `python src/analytics_dashboard.py`
- [ ] Abriu `digests/analytics.html` no navegador
- [ ] Viu os gráficos e recomendações
- [ ] Entendeu quais indústrias/ATS têm melhor performance
- [ ] Planeja ajustes na rubrica baseado nos insights

Se tudo marcado, **Semana 9 está completa!** ✅

---

## Arquivos Gerados

Depois de rodar a análise:

- `digests/analytics.html` — Dashboard interativo
- `digests/analytics_report.json` — Dados brutos da análise

---

## Resumo: Sistema Completo Após Semana 9

```
PIPELINE AUTOMÁTICO (2x/dia no GitHub)
  ↓
Busca emails → Extrai vagas → Avalia fit → Gera digest → Envia email
  ↓
Você aprova vagas
  ↓
Claude in Chrome preenche formulários
  ↓
Tracker registra status
  ↓
Dashboard mostra progresso
  ↓
ANALYTICS: Identifica padrões e otimiza processo
```

Você agora tem um **sistema completo, inteligente e data-driven** de automação de job hunting! 🚀
