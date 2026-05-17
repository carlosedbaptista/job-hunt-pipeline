"""
analytics_dashboard.py  —  Gera dashboard HTML com gráficos de análise
Mostra insights por indústria, ATS, tipo de vaga, etc
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.analytics_engine import (
    get_all_applications,
    generate_analytics_report,
    get_recommendations,
)


def generate_analytics_html(report: dict, recommendations: list) -> str:
    """Gera HTML do dashboard de analytics."""
    
    by_industry = report["dimensions"]["by_industry"]
    by_ats = report["dimensions"]["by_ats"]
    by_job = report["dimensions"]["by_job_type"]
    overall = report["overall_metrics"]
    
    # Prepara dados pra gráficos
    industry_labels = list(by_industry.keys())
    industry_responses = [by_industry[k]["response_rate_percent"] for k in industry_labels]
    
    ats_labels = list(by_ats.keys())
    ats_responses = [by_ats[k]["response_rate_percent"] for k in ats_labels]
    
    job_labels = list(by_job.keys())
    job_responses = [by_job[k]["response_rate_percent"] for k in job_labels]

    html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunt Analytics</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
            max-width: 1400px;
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
        }}

        .subtitle {{
            color: #666;
            font-size: 14px;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        .metric {{
            text-align: center;
        }}

        .metric-number {{
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }}

        .metric-label {{
            color: #666;
            font-size: 13px;
            text-transform: uppercase;
        }}

        .charts {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
            margin-bottom: 30px;
        }}

        .chart-container {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            position: relative;
            height: 400px;
        }}

        .chart-container h2 {{
            color: #333;
            font-size: 16px;
            margin-bottom: 20px;
        }}

        canvas {{
            max-height: 350px;
        }}

        .recommendations {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}

        .recommendations h2 {{
            color: #333;
            margin-bottom: 20px;
        }}

        .recommendation-item {{
            padding: 15px;
            margin-bottom: 15px;
            background-color: #f9f9f9;
            border-left: 4px solid #667eea;
            border-radius: 4px;
        }}

        .recommendation-item p {{
            color: #555;
            margin: 0;
        }}

        footer {{
            text-align: center;
            color: white;
            font-size: 12px;
            margin-top: 40px;
        }}

        .empty {{
            background: white;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            color: #999;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Job Hunt Analytics Dashboard</h1>
            <p class="subtitle">
                Carlos Eduardo Duarte Baptista • Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M')}
            </p>
        </header>

        <div class="grid">
            <div class="card metric">
                <div class="metric-label">Total Aplicações</div>
                <div class="metric-number">{overall['total_applications']}</div>
            </div>

            <div class="card metric">
                <div class="metric-label">Respostas</div>
                <div class="metric-number">{overall['total_responses']}</div>
            </div>

            <div class="card metric">
                <div class="metric-label">Taxa de Resposta</div>
                <div class="metric-number">{overall['overall_response_rate']:.1f}%</div>
            </div>

            <div class="card metric">
                <div class="metric-label">Tempo Médio Resposta</div>
                <div class="metric-number">{report.get('response_time', {}).get('avg_days', 0):.0f}d</div>
            </div>
        </div>

        <div class="charts">
            <div class="chart-container">
                <h2>Taxa de Resposta por Indústria</h2>
                <canvas id="industryChart"></canvas>
            </div>

            <div class="chart-container">
                <h2>Taxa de Resposta por ATS</h2>
                <canvas id="atsChart"></canvas>
            </div>

            <div class="chart-container">
                <h2>Taxa de Resposta por Tipo de Vaga</h2>
                <canvas id="jobChart"></canvas>
            </div>

            <div class="chart-container">
                <h2>Aplicações por Indústria</h2>
                <canvas id="industryCountChart"></canvas>
            </div>
        </div>

        {generate_recommendations_html(recommendations) if recommendations else '<div class="empty">Sem recomendações ainda — adicione mais aplicações!</div>'}

        <footer>
            Job Hunt Pipeline • Semana 9 Analytics • © 2026
        </footer>
    </div>

    <script>
        // Gráfico: Taxa de Resposta por Indústria
        new Chart(document.getElementById('industryChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(industry_labels)},
                datasets: [{{
                    label: 'Taxa de Resposta (%)',
                    data: {json.dumps(industry_responses)},
                    backgroundColor: '#667eea',
                    borderColor: '#667eea',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{legend: {{display: false}}}}
            }}
        }});

        // Gráfico: Taxa de Resposta por ATS
        new Chart(document.getElementById('atsChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(ats_labels)},
                datasets: [{{
                    label: 'Taxa de Resposta (%)',
                    data: {json.dumps(ats_responses)},
                    backgroundColor: '#764ba2',
                    borderColor: '#764ba2',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{legend: {{display: false}}}}
            }}
        }});

        // Gráfico: Taxa de Resposta por Tipo de Vaga
        new Chart(document.getElementById('jobChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(job_labels)},
                datasets: [{{
                    label: 'Taxa de Resposta (%)',
                    data: {json.dumps(job_responses)},
                    backgroundColor: '#32CD32',
                    borderColor: '#32CD32',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{legend: {{display: false}}}}
            }}
        }});

        // Gráfico: Contagem por Indústria
        new Chart(document.getElementById('industryCountChart'), {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(industry_labels)},
                datasets: [{{
                    data: {json.dumps([by_industry[k]['total_applications'] for k in industry_labels])},
                    backgroundColor: [
                        '#667eea',
                        '#764ba2',
                        '#32CD32',
                        '#FFA500',
                        '#FF6B6B',
                        '#4ECDC4'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false
            }}
        }});
    </script>
</body>
</html>
"""

    return html


def generate_recommendations_html(recommendations: list) -> str:
    """Gera seção HTML com recomendações."""
    if not recommendations:
        return ""

    items = "\n".join(
        f'<div class="recommendation-item"><p>{rec}</p></div>' for rec in recommendations
    )

    return f"""
        <div class="recommendations">
            <h2>💡 Recomendações</h2>
            {items}
        </div>
    """


def save_analytics_dashboard():
    """Gera e salva o dashboard de analytics."""
    apps = get_all_applications()

    if not apps:
        print("❌ Nenhuma aplicação registrada ainda")
        return False

    print(f"Analisando {len(apps)} aplicação(ões)...")

    report = generate_analytics_report(apps)
    recommendations = get_recommendations(report)

    html = generate_analytics_html(report, recommendations)

    os.makedirs("digests", exist_ok=True)
    output_path = "digests/analytics.html"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Salva JSON também
    json_path = "digests/analytics_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Analytics dashboard gerado:")
    print(f"   • {output_path}")
    print(f"   • {json_path}")

    return True


if __name__ == "__main__":
    success = save_analytics_dashboard()
    sys.exit(0 if success else 1)
