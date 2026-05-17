"""
followup_sender.py  —  Envia follow-ups por email
Busca aplicações > 7 dias sem resposta + email de contato
"""

import sqlite3
import os
import sys
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.followup_writer import generate_followup_email_package

DB_PATH = "tracker/jobs.db"


def get_old_applications(days_threshold: int = 7) -> list[dict]:
    """
    Busca aplicações que:
    1. Não receberam resposta ainda
    2. Foram enviadas > days_threshold dias atrás
    3. Têm email de contato do recrutador
    4. Não foram feitos follow-up ainda (ou última tentativa > 3 dias)
    """
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).isoformat()
    
    # SQL pra buscar candidatos elegíveis
    query = """
    SELECT 
        id,
        empresa,
        titulo,
        date_applied,
        recruiter_email,
        last_followup_date,
        followup_count
    FROM applications
    WHERE 
        response_type IS NULL  -- Sem resposta ainda
        AND date_applied < ?   -- Mais de 7 dias atrás
        AND recruiter_email IS NOT NULL  -- Tem email
        AND recruiter_email != ''
        AND (
            last_followup_date IS NULL  -- Nunca foi feito follow-up
            OR last_followup_date < ?   -- Última tentativa foi > 3 dias atrás
        )
    ORDER BY date_applied ASC
    """
    
    cutoff_3_days = (datetime.now() - timedelta(days=3)).isoformat()
    
    try:
        apps = conn.execute(query, (cutoff_date, cutoff_3_days)).fetchall()
        conn.close()
        return [dict(app) for app in apps]
    except Exception as e:
        print(f"❌ Erro ao buscar aplicações: {e}")
        conn.close()
        return []


def update_followup_status(app_id: int, success: bool = True):
    """Atualiza tracker com info de follow-up enviado."""
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        conn.execute("""
            UPDATE applications
            SET 
                last_followup_date = ?,
                followup_count = COALESCE(followup_count, 0) + 1
            WHERE id = ?
        """, (datetime.now().isoformat(), app_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Erro ao atualizar follow-up: {e}")
        conn.close()
        return False


def send_followup_email(
    to_email: str,
    subject: str,
    body: str,
    sender_email: str,
    app_password: str,
) -> bool:
    """Envia follow-up por email via Gmail SMTP."""
    
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = to_email
        
        # Cria versão com rodapé
        full_body = f"""{body}

---
Best regards,
Carlos Eduardo Duarte Baptista
+41 78 261 34 74
carlosedbaptista@gmail.com
linkedin.com/in/carlosedbaptista

Swiss Work Permit B | Wallisellen, Zurich
"""
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="white-space: pre-wrap;">{full_body}</div>
        </body>
        </html>
        """
        
        message.attach(MIMEText(full_body, "plain"))
        message.attach(MIMEText(html_body, "html"))
        
        server.sendmail(sender_email, to_email, message.as_string())
        server.quit()
        
        return True
    
    except Exception as e:
        print(f"❌ Erro ao enviar email: {e}")
        return False


def send_followups():
    """Envia follow-ups para todas as aplicações elegíveis."""
    
    print("\n" + "="*70)
    print("FOLLOW-UP SENDER — Semana 10")
    print("="*70 + "\n")
    
    # Pega credenciais
    sender_email = os.environ.get("GMAIL_SENDER", "carlosedbaptista@gmail.com")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    
    if not app_password:
        print("⚠️  GMAIL_APP_PASSWORD não configurado")
        return False
    
    # Busca aplicações elegíveis
    old_apps = get_old_applications(days_threshold=7)
    
    if not old_apps:
        print("✅ Nenhuma aplicação elegível para follow-up")
        return True
    
    print(f"📧 Encontradas {len(old_apps)} aplicação(ões) elegível(is):\n")
    
    sent_count = 0
    
    for app in old_apps:
        app_id = app["id"]
        empresa = app["empresa"]
        titulo = app["titulo"]
        recruiter_email = app["recruiter_email"]
        date_applied = app["date_applied"]
        
        # Calcula dias passados
        app_date = datetime.fromisoformat(date_applied)
        dias_passados = (datetime.now() - app_date).days
        
        print(f"{sent_count + 1}. {empresa} — {titulo}")
        print(f"   Email: {recruiter_email}")
        print(f"   Dias sem resposta: {dias_passados}")
        
        # Gera follow-up
        followup_package = generate_followup_email_package({
            "empresa": empresa,
            "titulo": titulo,
            "dias_sem_resposta": dias_passados,
            "date_applied": date_applied,
        })
        
        if not followup_package:
            print(f"   ❌ Erro ao gerar follow-up\n")
            continue
        
        # Envia email
        success = send_followup_email(
            to_email=recruiter_email,
            subject=followup_package["subject"],
            body=followup_package["body"],
            sender_email=sender_email,
            app_password=app_password,
        )
        
        if success:
            # Atualiza tracker
            update_followup_status(app_id)
            print(f"   ✅ Follow-up enviado\n")
            sent_count += 1
        else:
            print(f"   ❌ Erro ao enviar email\n")
    
    print("="*70)
    print(f"✅ {sent_count} follow-up(s) enviado(s)")
    print("="*70 + "\n")
    
    return True


if __name__ == "__main__":
    success = send_followups()
    sys.exit(0 if success else 1)
