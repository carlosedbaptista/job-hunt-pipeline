"""
SEMANA 6: CLAUDE IN CHROME - GUIA DE USO COMPLETO

Este guia explica como usar Claude in Chrome pra preencher formulários automaticamente.
"""

# ═════════════════════════════════════════════════════════════════════════════
# VISÃO GERAL
# ═════════════════════════════════════════════════════════════════════════════

"""
FLUXO COMPLETO:

1. Pipeline Semana 2-4 (já feito):
   Emails → Parsing → Avaliação → Digest → Aprovação

2. NOVO - Semana 5:
   Tracker + Dashboard → Monitor respostas

3. NOVO - Semana 6 (Claude in Chrome):
   Aprovação → Gera Guia → Você abre Claude in Chrome → 
   Claude preenche formulário → Você confirma submissão →
   Tracker atualiza status
"""

# ═════════════════════════════════════════════════════════════════════════════
# PREPARAÇÃO
# ═════════════════════════════════════════════════════════════════════════════

"""
PRÉ-REQUISITOS:

1. ✅ Claude in Chrome instalado
   - Chrome Web Store: "Claude in Chrome" by Anthropic
   - Atalho: Alt+C (ou Cmd+C no Mac)

2. ✅ Seu CV atualizado
   - Arquivo: Carlos_Baptista_CV_Master_v3.docx
   - Deve estar acessível no computador

3. ✅ Cover letters geradas
   - Pela Semana 3 (cover_letter_writer.py)
   - Uma por vaga aprovada
"""

# ═════════════════════════════════════════════════════════════════════════════
# PASSO A PASSO: APLICAR COM CLAUDE IN CHROME
# ═════════════════════════════════════════════════════════════════════════════

"""
PASSO 1: Aprovar vagas
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Veja o digest:
  $ python agents/digest_generator.py

Aprove as que quer:
  $ python src/approval_handler.py --approve "1,3,5"

Resultado: arquivo digests/approvals_latest.json com suas escolhas


PASSO 2: Gerar guias de preenchimento
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Roda o orquestrador:
  $ python src/apply_automation.py

O script vai:
  1. Carregar suas aprovações
  2. Gerar guias estruturados (1 por vaga)
  3. Mostrar prompts otimizados pra Claude in Chrome
  4. Guiá-lo através do processo de preenchimento


PASSO 3: Usar Claude in Chrome
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Para cada vaga:

a) Abra a URL no navegador (vem no terminal)

b) Ative Claude in Chrome:
   - Atalho: Alt+C (ou Cmd+C no Mac)
   - Abrirá um painel no lado direito

c) COPIE o prompt do terminal

d) COLE no chat do Claude in Chrome

e) Claude vai:
   - Analisar o formulário
   - Preencher campos automaticamente
   - Manter você atualizado do progresso
   - Pedir aprovação antes de submeter

f) Revise as informações

g) Confirme a submissão

h) Claude in Chrome vai submeter o formulário

i) Volta pro terminal e pressiona ENTER


PASSO 4: Registrar no Tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Automático! Quando pressiona ENTER:
  - apply_automation.py registra a aplicação no SQLite
  - Status: "submitted_via_chrome"
  - Timestamp registrado


PASSO 5: Ver status no Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Após terminar todas as aplicações:
  $ python src/dashboard.py

Abre digests/dashboard.html no navegador
  - Ver todas as suas aplicações
  - Ver status (enviado, respondido, etc)
  - Ver taxa de resposta
"""

# ═════════════════════════════════════════════════════════════════════════════
# TIPOS DE FORMULÁRIOS
# ═════════════════════════════════════════════════════════════════════════════

"""
Claude in Chrome consegue lidar com:

✅ WORKDAY
   - Formulários estruturados e formais
   - Campos bem identificados
   - Claude detecta e preenche automaticamente

✅ GREENHOUSE
   - Moderno e clean
   - Campos progressivos
   - Claude segue o fluxo passo a passo

✅ LEVER
   - Mobile-friendly
   - Intuitivo
   - Claude navega bem

✅ TALENTSOFT
   - Complexos mas estruturados
   - Claude processa sequencialmente

✅ FORMULÁRIOS GENÉRICOS
   - Qualquer ATS customizado
   - Claude tenta detectar campos
   - Pede sua confirmação em campos ambíguos

IMPORTANTE: Claude SEMPRE pede sua confirmação antes de submeter!
"""

# ═════════════════════════════════════════════════════════════════════════════
# TROUBLESHOOTING
# ═════════════════════════════════════════════════════════════════════════════

"""
PROBLEMA: Claude in Chrome não preenche campos
SOLUÇÃO:
  - Verifique se o formulário carregou completamente
  - Tente pedir pra Claude "scroll down" e tente novamente
  - Se campo é obrigatório, preencha manualmente

PROBLEMA: Site pede CAPTCHA
SOLUÇÃO:
  - Resolva o CAPTCHA manualmente
  - Diga pro Claude: "CAPTCHA resolvido, continua"

PROBLEMA: CV não faz upload
SOLUÇÃO:
  - Verifique o caminho do arquivo
  - Certifique que é .docx ou .pdf
  - Tente fazer upload manualmente, depois diga pro Claude confirmar

PROBLEMA: Aplicação não foi registrada no tracker
SOLUÇÃO:
  - Volta pro terminal e pressiona ENTER (é importante!)
  - Se não conseguir, roda manualmente:
    python agents/tracker_updater.py record digests/approvals_latest.json
"""

# ═════════════════════════════════════════════════════════════════════════════
# EXEMPLO REAL
# ═════════════════════════════════════════════════════════════════════════════

"""
EXEMPLO: Aplicar na vaga "On - Athlete Strategy"

1. Digest mostra:
   1. [42/100] Kanton Zürich...
   2. [28/100] I&C Immo...

2. Aprova vaga 1:
   $ python src/approval_handler.py --approve "1"

3. Gera guia:
   $ python src/apply_automation.py

   Terminal mostra:
   ┌─────────────────────────────────────────┐
   │ VAGA 1: Kanton Zürich                   │
   │ Full Name: Carlos Eduardo Duarte Baptista
   │ Email: carlosedbaptista@gmail.com       │
   │ Phone: +41 78 261 34 74                 │
   │ ...                                     │
   │ 🔗 Link: https://...                    │
   └─────────────────────────────────────────┘

4. Abre link no navegador

5. Alt+C (ativa Claude in Chrome)

6. Copia prompt e cola no chat

7. Claude:
   "I'll fill out the application form for you.
    Let me analyze the form... [filling...]
    Please confirm: I'll upload your CV now?
    [Você: Yes]
    Form submitted! ✅"

8. Pressiona ENTER no terminal

9. ✅ Registrado no tracker

10. Dashboard atualiza: 1 aplicação enviada
"""

# ═════════════════════════════════════════════════════════════════════════════
# PRÓXIMOS PASSOS
# ═════════════════════════════════════════════════════════════════════════════

"""
Após Semana 6, você tem:

✅ Pipeline automático de ingestão (Semana 2)
✅ Avaliação de fit (Semana 3)
✅ Digest diário (Semana 4)
✅ Tracker + Dashboard (Semana 5)
✅ Preenchimento de formulários com Claude (Semana 6)

PRÓXIMAS OTIMIZAÇÕES (Opcional):

Semana 7: Scheduler
  - Roda pipeline automaticamente todo dia às 8:00
  - Gmail → Claude → Dashboard → Notificação

Semana 8: Email Responses
  - Monitor automático de respostas
  - Classificação: entrevista, rejeição, positivo
  - Alerta quando receber resposta

Semana 9: Analytics
  - Qual tipo de vaga tem maior taxa de resposta?
  - Qual industria? Qual ATS?
  - Otimização da rubrica de fit
"""

# ═════════════════════════════════════════════════════════════════════════════
# REFERÊNCIA RÁPIDA
# ═════════════════════════════════════════════════════════════════════════════

"""
COMANDOS PRINCIPAIS:

# Ver digest
python agents/digest_generator.py

# Aprovar vagas
python src/approval_handler.py --approve "1,3,5"

# Gerar guias e começar aplicações com Claude in Chrome
python src/apply_automation.py

# Ver dashboard
python src/dashboard.py

# Ver status das aplicações
python agents/tracker_updater.py stats

# Listar todas as aplicações
python agents/tracker_updater.py list

# Monitor de respostas de recrutadores
python agents/email_monitor.py

# Rodar pipeline completo (Semana 2-6)
python src/week4_pipeline.py
"""
