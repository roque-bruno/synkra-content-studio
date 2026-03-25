"""
Relatorio Semanal PDF — Gera relatorio automatico para a diretoria.

Inclui:
- Resumo executivo (pecas produzidas, aprovadas, publicadas)
- Metricas de engajamento por plataforma
- Top posts da semana
- Custo total e ROI estimado
- Insights do feedback loop
- Proximos passos recomendados

Gera HTML que pode ser convertido em PDF via weasyprint ou similar.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class WeeklyReport:
    """Gerador de relatorio semanal."""

    def __init__(self, db=None, budget_tracker=None, feedback_loop=None):
        self.db = db
        self.budget_tracker = budget_tracker
        self.feedback_loop = feedback_loop

    def generate(
        self,
        week_id: str = "",
        brand: str = "",
    ) -> dict:
        """
        Gera dados do relatorio semanal.

        Returns:
            dict com todas as secoes do relatorio
        """
        if self.db is None:
            return {"error": "Database nao configurado"}

        report = {
            "generated_at": datetime.now().isoformat(),
            "week_id": week_id or datetime.now().strftime("%Y-W%W"),
            "brand": brand or "todas",
        }

        # 1. Resumo de producao
        pieces = self.db.list_pieces(brand=brand)
        report["production"] = {
            "total_pieces": len(pieces),
            "by_stage": {},
            "by_platform": {},
            "by_format": {},
        }

        for piece in pieces:
            stage = piece.get("stage", "unknown")
            platform = piece.get("platform", "unknown")
            fmt = piece.get("format", "unknown")
            report["production"]["by_stage"][stage] = report["production"]["by_stage"].get(stage, 0) + 1
            report["production"]["by_platform"][platform] = report["production"]["by_platform"].get(platform, 0) + 1
            report["production"]["by_format"][fmt] = report["production"]["by_format"].get(fmt, 0) + 1

        # 2. Metricas de engajamento
        metrics = self.db.list_metrics()
        total_impressions = sum(m.get("impressions", 0) for m in metrics)
        total_reach = sum(m.get("reach", 0) for m in metrics)
        total_engagement = sum(m.get("engagement", 0) for m in metrics)

        report["engagement"] = {
            "total_posts_tracked": len(metrics),
            "total_impressions": total_impressions,
            "total_reach": total_reach,
            "total_engagement": total_engagement,
            "avg_engagement_rate": round(
                (total_engagement / total_reach * 100) if total_reach > 0 else 0, 2
            ),
        }

        # 3. Top posts (por engajamento)
        sorted_metrics = sorted(metrics, key=lambda m: m.get("engagement", 0), reverse=True)
        report["top_posts"] = sorted_metrics[:5]

        # 4. Custos
        if self.budget_tracker:
            budget = self.budget_tracker.get_month_summary()
            report["costs"] = {
                "month_total_usd": budget.get("total_usd", 0),
                "month_total_brl": budget.get("total_brl_estimate", 0),
                "budget_used_pct": budget.get("percentage_used", 0),
                "by_category": budget.get("by_category", {}),
            }
        else:
            report["costs"] = {"month_total_usd": 0}

        # 5. Insights do feedback loop
        if self.feedback_loop:
            analysis = self.feedback_loop.analyze_performance(brand=brand)
            report["insights"] = analysis.get("insights", [])
            report["recommendations"] = self.feedback_loop.get_briefing_recommendations(
                brand=brand or "salk"
            ).get("recommendations", [])
        else:
            report["insights"] = []
            report["recommendations"] = []

        # 6. Reviews
        reviews = self.db.list_reviews()
        approved = len([r for r in reviews if r.get("verdict") == "approved"])
        rejected = len([r for r in reviews if r.get("verdict") == "rejected"])
        report["reviews"] = {
            "total": len(reviews),
            "approved": approved,
            "rejected": rejected,
            "approval_rate": round(
                approved / (approved + rejected) * 100 if (approved + rejected) > 0 else 0, 1
            ),
        }

        return report

    def generate_html(
        self,
        week_id: str = "",
        brand: str = "",
    ) -> str:
        """Gera relatorio em formato HTML (pode ser convertido em PDF)."""
        data = self.generate(week_id=week_id, brand=brand)

        if "error" in data:
            return f"<html><body><h1>Erro: {data['error']}</h1></body></html>"

        prod = data.get("production", {})
        eng = data.get("engagement", {})
        costs = data.get("costs", {})
        reviews = data.get("reviews", {})

        # Top posts HTML
        top_posts_html = ""
        for i, post in enumerate(data.get("top_posts", []), 1):
            top_posts_html += f"""
            <tr>
                <td>{i}</td>
                <td>{post.get('platform', '-')}</td>
                <td>{post.get('engagement', 0)}</td>
                <td>{post.get('impressions', 0)}</td>
                <td>{post.get('reach', 0)}</td>
            </tr>"""

        # Insights HTML
        insights_html = ""
        for insight in data.get("insights", []):
            insights_html += f"<li><strong>{insight.get('type', '')}:</strong> {insight.get('insight', '')}</li>"

        # Recommendations HTML
        recs_html = ""
        for rec in data.get("recommendations", []):
            recs_html += f"<li>{rec}</li>"

        html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Relatorio Semanal — {data.get('week_id', '')}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #333; }}
        h1 {{ color: #1a1a2e; border-bottom: 3px solid #0066cc; padding-bottom: 10px; }}
        h2 {{ color: #16213e; margin-top: 30px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
        .summary-card {{ background: #f8f9fa; border-radius: 8px; padding: 15px; text-align: center; }}
        .summary-card .number {{ font-size: 2em; font-weight: bold; color: #0066cc; }}
        .summary-card .label {{ font-size: 0.9em; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f0f0f0; font-weight: 600; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #999; font-size: 0.8em; }}
    </style>
</head>
<body>
    <h1>Relatorio Semanal — {data.get('week_id', '')}</h1>
    <p>Marca: <strong>{data.get('brand', 'todas').title()}</strong> | Gerado em: {data.get('generated_at', '')[:10]}</p>

    <div class="summary-grid">
        <div class="summary-card">
            <div class="number">{prod.get('total_pieces', 0)}</div>
            <div class="label">Pecas Produzidas</div>
        </div>
        <div class="summary-card">
            <div class="number">{eng.get('total_engagement', 0)}</div>
            <div class="label">Engajamento Total</div>
        </div>
        <div class="summary-card">
            <div class="number">{eng.get('avg_engagement_rate', 0)}%</div>
            <div class="label">Taxa de Engajamento</div>
        </div>
        <div class="summary-card">
            <div class="number">R${costs.get('month_total_brl', 0):.0f}</div>
            <div class="label">Custo Mensal</div>
        </div>
    </div>

    <h2>Producao</h2>
    <table>
        <tr><th>Stage</th><th>Quantidade</th></tr>
        {"".join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in prod.get('by_stage', {}).items())}
    </table>

    <h2>Top Posts</h2>
    <table>
        <tr><th>#</th><th>Plataforma</th><th>Engajamento</th><th>Impressoes</th><th>Alcance</th></tr>
        {top_posts_html or '<tr><td colspan="5">Sem dados</td></tr>'}
    </table>

    <h2>Revisoes</h2>
    <p>Aprovadas: <strong>{reviews.get('approved', 0)}</strong> | Rejeitadas: <strong>{reviews.get('rejected', 0)}</strong> | Taxa: <strong>{reviews.get('approval_rate', 0)}%</strong></p>

    <h2>Insights</h2>
    <ul>{insights_html or '<li>Sem insights disponiveis (colete mais metricas)</li>'}</ul>

    <h2>Recomendacoes</h2>
    <ul>{recs_html or '<li>Manter plano editorial atual</li>'}</ul>

    <h2>Custos</h2>
    <p>Total mensal: <strong>${costs.get('month_total_usd', 0):.2f} USD</strong> ({costs.get('budget_used_pct', 0):.1f}% do orcamento)</p>

    <div class="footer">
        Salk Content Studio v2.0 — Manager Grupo | Relatorio gerado automaticamente
    </div>
</body>
</html>"""

        return html
