# Semana 7: GitHub Actions Scheduler — Setup Completo

## O que você fez

Criou um **workflow do GitHub Actions** que:
- ✅ Roda automaticamente todo dia às **7:00 AM** (hora da Suíça)
- ✅ Executa o pipeline completo (ingest → parse → eval → digest)
- ✅ Gera o dashboard automaticamente
- ✅ Faz commit dos arquivos atualizados no repo

---

## Configuração Necessária

### PASSO 1: Adicionar Secret no GitHub

Seu workflow já está configurado pra ler a chave da Anthropic API de um **Secret** do GitHub.

1. Vá em: https://github.com/seu-usuario/job-hunt-pipeline/settings/secrets/actions

2. Clica em **"New repository secret"**

3. Nome: `ANTHROPIC_API_KEY`
   Valor: `sk-ant-seu-chave-aqui`

4. Clica em **"Add secret"**

✅ Pronto! GitHub Actions agora consegue rodar Claude.

---

### PASSO 2: Problema do Gmail API (Importante!)

⚠️ **AVISO:** GitHub Actions roda em servidor Linux sem acesso a seu computador.

**Problema:**
- Gmail API precisa de `token.pickle` (gerado no seu computador)
- GitHub não consegue acessar seu arquivo local

**Soluções:**

#### Opção A: Rodar localmente via Cron/Task Scheduler (Recomendado)
Se você quer garantir que funciona:

**No Windows:**
1. Abra "Task Scheduler"
2. Cria uma task que roda: `python src/week4_pipeline.py`
3. Agenda pra 7:00 AM todos os dias

**No Mac/Linux:**
```bash
# Cria um cron job
crontab -e

# Adiciona (7 AM todo dia):
0 7 * * * cd ~/job-hunt-pipeline && python src/week4_pipeline.py
```

#### Opção B: GitHub Actions + Fallback Manual
Deixa o GitHub Actions ligado, mas:
- Se falhar (por causa do Gmail), você roda manualmente no fim de semana
- Pelo menos gera digest com vagas antigos (útil mesmo sem novos emails)

#### Opção C: Usar Google Cloud para Gmail (Avançado)
- Configura Google Cloud Scheduler
- Dispara uma função que roda o pipeline
- Caro, mas 100% automático

---

## Teste o Workflow

### Teste 1: Rodar Manualmente no GitHub

1. Vai em: https://github.com/seu-usuario/job-hunt-pipeline/actions

2. Clica em **"Job Hunt Daily Pipeline"**

3. Clica em **"Run workflow"** → **"Run workflow"**

4. Aguarda 2-5 minutos

5. Se tiver ✅ verde = sucesso, se ❌ vermelho = falhou

### Teste 2: Verificar os arquivos atualizados

Se rodou com sucesso, deve ter feito commit com:
- `digests/digest_latest.json` atualizado
- `digests/dashboard.html` atualizado

---

## Cronograma (Cron)

Seu workflow está configurado pra:

```
0 5 * * *
│ │ │ │ └─ Dia da semana (0-6, 0 é domingo)
│ │ │ └─── Mês (1-12)
│ │ └───── Dia do mês (1-31)
│ └─────── Hora (UTC, 0-23)
└───────── Minuto (0-59)
```

**0 5 * * * = 5:00 AM UTC = 7:00 AM CEST (verão na Suíça)**

Se quiser mudar pra outra hora, edita `.github/workflows/job-hunt-scheduler.yml`

Exemplos:
- `0 6 * * *` = 8:00 AM CEST
- `0 8 * * *` = 10:00 AM CEST
- `0 20 * * *` = 22:00 (10 PM) CEST

---

## O que acontece quando roda

1. ✅ GitHub faz pull do seu repo
2. ✅ Instala dependências (pip install -r requirements.txt)
3. ✅ Roda `python src/week4_pipeline.py`
   - Busca emails do Gmail
   - Parsia vagas com Claude
   - Avalia fit
   - Gera digest
4. ✅ Faz commit e push dos arquivos atualizados
5. ✅ Você recebe notificação (opcional, via GitHub)

---

## Logs e Debugging

Se algo der errado:

1. Vá em: GitHub → Actions → Job Hunt Daily Pipeline

2. Clica no run que falhou

3. Clica em **"job-hunt-pipeline"**

4. Vê o output (onde está o erro)

Erros comuns:
- `ModuleNotFoundError` = requirements.txt não tem um pacote
- `authentication_error` = Secret não foi adicionado
- `Gmail error` = token.pickle não está acessível (esperado)

---

## Recomendação Final

**Use GitHub Actions APENAS como backup.** 

Para garantir que funciona 100%, configure um **Cron Job local** (Option A acima) no seu computador.

Assim:
- ✅ GitHub Actions roda (gera digest mesmo sem novos emails)
- ✅ Cron local roda (busca novos emails toda manhã)
- ✅ Sistema robusto com redundância

---

## Próximas Otimizações (Semana 8+)

- [ ] Configurar notificações (email quando há novas vagas)
- [ ] Adicionar Google Cloud Function pra Gmail (remover necessidade de token.pickle)
- [ ] Criar webhook pra enviar digest por email
- [ ] Analytics: qual tipo de vaga tem melhor resposta?
