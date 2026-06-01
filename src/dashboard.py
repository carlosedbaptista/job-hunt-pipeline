"""
dashboard.py  —  Gera dashboard HTML interativo
Mostra status das aplicações, estatísticas, timeline
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.tracker_updater import get_all_applications, get_stats


def generate_html_dashboard() -> str:
    """Gera HTML interativo do dashboard."""
    stats = get_stats()
    apps = get_all_applications()

    # Calcula datas e tempos
    if apps:
        first_app = datetime.fromisoformat(apps[-1]["date_applied"])
        days_active = (datetime.now() - first_app).days
    else:
        days_active = 0

    # Mapeia status para cores
    status_colors = {
        "sent": "#FFA500",  # orange
        "rejected": "#DC143C",  # crimson
        "interview_scheduled": "#32CD32",  # lime green
        "positive_response": "#00AA00",  # green
        "awaiting_info": "#4169E1",  # royal blue
    }

    html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunt Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        h1 {{
            color: #667eea;
            margin-bottom: 10px;
            font-size: 2em;
        }}

        .subtitle {{
            color: #666;
            font-size: 14px;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .stat-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
        }}

        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }}

        .stat-label {{
            color: #666;
            font-size: 14px;
            text-transform: uppercase;
        }}

        .applications-section {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        h2 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 1.5em;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
        }}

        th {{
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #333;
            border-bottom: 2px solid #ddd;
        }}

        td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}

        tr:hover {{
            background: #fafafa;
        }}

        .status-badge {{
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            color: white;
            text-transform: uppercase;
        }}

        .status-sent {{
            background: #FFA500;
        }}

        .status-rejected {{
            background: #DC143C;
        }}

        .status-interview {{
            background: #32CD32;
        }}

        .status-positive {{
            background: #00AA00;
        }}

        .status-awaiting {{
            background: #4169E1;
        }}

        .empresa {{
            font-weight: 600;
            color: #333;
        }}

        .date {{
            color: #999;
            font-size: 13px;
        }}

        .empty {{
            text-align: center;
            padding: 40px;
            color: #999;
        }}

        footer {{
            margin-top: 30px;
            text-align: center;
            color: white;
            font-size: 12px;
        }}

        .response-rate {{
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: conic-gradient(
                #32CD32 0deg {stats['response_rate_percent']/100 * 360}deg,
                #ddd {stats['response_rate_percent']/100 * 360}deg
            );
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 20px;
            margin: 10px auto;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Job Hunt Dashboard</h1>
            <p class="subtitle">
                Carlos Eduardo Duarte Baptista • Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M')}
            </p>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Aplicações</div>
                <div class="stat-number">{stats['total_applications']}</div>
            </div>

            <div class="stat-card">
                <div class="stat-label">Pendentes</div>
                <div class="stat-number" style="color: #FFA500;">{stats['pending']}</div>
            </div>

            <div class="stat-card">
                <div class="stat-label">Respondidas</div>
                <div class="stat-number" style="color: #32CD32;">{stats['responded']}</div>
            </div>

            <div class="stat-card">
                <div class="stat-label">Taxa de Resposta</div>
                <div class="response-rate">{stats['response_rate_percent']:.1f}%</div>
            </div>

            <div class="stat-card">
                <div class="stat-label">Entrevistas</div>
                <div class="stat-number" style="color: #32CD32;">{stats['interviews']}</div>
            </div>

            <div class="stat-card">
                <div class="stat-label">Rejeições</div>
                <div class="stat-number" style="color: #DC143C;">{stats['rejections']}</div>
            </div>
        </div>

        <div class="applications-section">
            <h2>Histórico de Aplicações</h2>
            
            {generate_applications_table(apps) if apps else '<div class="empty">Nenhuma aplicação registrada ainda</div>'}
        </div>

        <footer>
            Job Hunt Pipeline • Carlos Eduardo Duarte Baptista • © 2026
        </footer>
    </div>
</body>
</html>
"""

    return html


def generate_applications_table(apps: list) -> str:
    """Gera a tabela HTML com as aplicações."""
    status_map = {
        "sent": ("ENVIADO", "status-sent"),
        "rejected": ("REJEITADO", "status-rejected"),
        "interview_scheduled": ("ENTREVISTA", "status-interview"),
        "positive_response": ("POSITIVO", "status-positive"),
        "awaiting_info": ("AGUARDANDO", "status-awaiting"),
    }

    rows = []
    for app in apps:
        status = app.get("status", "sent")
        status_label, status_class = status_map.get(status, ("DESCONHECIDO", ""))

        date_applied = datetime.fromisoformat(
            app["date_applied"]
        ).strftime("%d/%m")

        response_info = ""
        if app.get("response_date"):
            response_date = datetime.fromisoformat(
                app["response_date"]
            ).strftime("%d/%m")
            response_info = f"<br><small>{response_date}</small>"

        rows.append(f"""
            <tr>
                <td>
                    <div class="empresa">{app['empresa']}</div>
                    <div class="date">{app['titulo'][:40]}</div>
                </td>
                <td class="date">{date_applied}</td>
                <td>
                    <span class="status-badge {status_class}">{status_label}</span>
                    {response_info}
                </td>
                <td>
                    {app.get('notes', '-')}
                </td>
            </tr>
        """)

    return f"""
        <table>
            <thead>
                <tr>
                    <th>Empresa & Título</th>
                    <th>Data</th>
                    <th>Status</th>
                    <th>Notas</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    """


def save_dashboard():
    """Gera e salva o dashboard HTML."""
    os.makedirs("digests", exist_ok=True)

    html = generate_html_dashboard()
    
    output_path = "digests/dashboard.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


if __name__ == "__main__":
    output = save_dashboard()
    print(f"Dashboard gerado: {output}")
    print(f"   Abra no navegador: file://{os.path.abspath(output)}")
