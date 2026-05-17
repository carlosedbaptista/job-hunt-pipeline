# Email Notifications — Setup Completo

## O que você tem agora

Um **Email Notifier** que:
- ✅ Lê o digest gerado pelo pipeline
- ✅ Formata como email HTML bonito
- ✅ Envia pra seu email via Gmail SMTP
- ✅ Roda automaticamente após o digest ser gerado

---

## Configuração Necessária

### PASSO 1: Gerar App Password do Gmail

Gmail não permite acesso direto com senha normal (por segurança). Você precisa de um **App Password**.

**Como gerar:**

1. Vá em: https://myaccount.google.com/apppasswords

2. Se pediu 2FA, ative (é seguro)

3. Selecione:
   - App: **Mail**
   - Device: **Windows/Mac/Linux**

4. Clique em **Generate**

5. Gmail vai gerar uma senha de **16 caracteres**
   - Exemplo: `abcd efgh ijkl mnop`
   - **Copie e guarde num lugar seguro**

⚠️ **IMPORTANTE:** Isso é diferente da sua senha do Gmail!

---

### PASSO 2: Adicionar Secrets no GitHub

Você precisa adicionar 2 secrets:

1. Vai em: https://github.com/seu-usuario/job-hunt-pipeline/settings/secrets/actions

2. Clica **"New repository secret"** (primeira vez)

3. Adiciona:

```
Nome: GMAIL_APP_PASSWORD
Valor: (a senha de 16 caracteres que gerou acima)
Exemplo: abcdefghijklmnop
```

4. Clica **"Add secret"**

5. Repete pra adicionar um segundo (opcional):

```
Nome: GMAIL_RECIPIENT
Valor: carlosedbaptista@gmail.com
```

---

### PASSO 3: Testar Localmente (Opcional)

Você pode testar o notifier no seu computador:

```bash
# Gera um digest primeiro
python agents/digest_generator.py

# Depois testa o notifier
export GMAIL_APP_PASSWORD="sua-senha-de-16-caracteres"
python agents/email_notifier.py
```

Se receber um email em poucos segundos, **deu certo!** ✅

---

### PASSO 4: Integrar no Pipeline

Edita o arquivo `.github/workflows/job-hunt-scheduler.yml`:

Encontra a seção `Run Job Hunt Pipeline` e adiciona ao final:

```yaml
      - name: Send email notification
        if: always()
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: |
          python agents/email_notifier.py || true
```

**Exemplo completo:**

```yaml
      - name: Run Job Hunt Pipeline
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python src/week4_pipeline.py --digest-only || true
          python src/dashboard.py || true

      - name: Send email notification
        if: always()
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: |
          python agents/email_notifier.py || true
```

---

## O que acontece agora

**A cada execução do pipeline (7 AM e 2 PM):**

1. ✅ Pipeline roda (ingest → parse → eval → digest)
2. ✅ Gera o digest (`digests/digest_latest.json`)
3. ✅ **Email Notifier lê o digest**
4. ✅ **Formata como HTML bonito**
5. ✅ **Envia pra você via Gmail**

**Você recebe no email:**

- Assunto: `📊 Job Hunt Digest — 17 de Maio`
- Corpo: 
  - Total de vagas encontradas
  - Top 5 vagas com score
  - Links pra cada vaga
  - Call-to-action pra abrir dashboard

---

## Troubleshooting

### Problema: "GMAIL_APP_PASSWORD não configurado"

**Solução:**
- Verifique se adicionou o secret no GitHub
- Espere 1-2 minutos depois de adicionar (GitHub precisa sincronizar)
- Teste rodando manualmente: GitHub → Actions → "Job Hunt Daily Pipeline" → "Run workflow"

### Problema: "Invalid credentials"

**Solução:**
- Verifique se a senha tem exatamente 16 caracteres
- Certifique que copiou corretamente (sem espaços extras)
- Tente gerar uma nova App Password

### Problema: "Email não chegou / foi pra spam"

**Solução:**
- Verifique a pasta de spam
- Adicione o email à sua lista de contatos confiáveis
- Se continuar indo pra spam, é normal com Google (assine como contato confiável)

### Problema: "SMTPAuthenticationError"

**Solução:**
- Certifique que ativou 2FA na conta Google
- Tente gerar uma nova App Password
- Use exatamente a senha de 16 caracteres

---

## Próximas Otimizações

### Notificação Condicional (apenas com novas vagas)

Se quiser receber email **apenas quando há novas vagas** (não todos os dias):

Edita `agents/email_notifier.py` e adiciona:

```python
def notify_digest():
    ...
    digest = load_digest()
    
    # Só envia se tiver vagas com score >= 75 ou >= 55
    apply_jobs = [j for j in digest.get("top_jobs", []) if j.get("score", 0) >= 55]
    
    if not apply_jobs:
        print("Nenhuma vaga interessante hoje, email não enviado")
        return True  # Sucesso, mas sem email
    
    ...
```

### Customizar Formato do Email

Edita `format_digest_as_html()` pra:
- Adicionar logo sua
- Mudar cores
- Incluir mais informações (red flags, etc)

---

## Checklist Final

- [ ] Gerou App Password do Gmail
- [ ] Adicionou `GMAIL_APP_PASSWORD` como Secret no GitHub
- [ ] Editou `.github/workflows/job-hunt-scheduler.yml` com o step de email
- [ ] Fez commit e push
- [ ] Testou rodando manualmente: GitHub → Actions → "Run workflow"
- [ ] Recebeu email com o digest

Se tudo marcado, **Semana 8 está completa!** ✅
