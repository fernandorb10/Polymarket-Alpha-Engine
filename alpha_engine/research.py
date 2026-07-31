import json
from openai import OpenAI
from .config import settings
from .models import Market, ResearchReport


SCHEMA = {
  "type": "object",
  "properties": {
    "probability_yes": {"type": "number", "minimum": 0, "maximum": 1},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "thesis": {"type": "string"},
    "counter_thesis": {"type": "string"},
    "catalysts": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}},
    "source_urls": {"type": "array", "items": {"type": "string"}},
    "freshness_hours": {"type": ["number", "null"]}
  },
  "required": ["probability_yes","confidence","thesis","counter_thesis","catalysts","risks","source_urls","freshness_hours"],
  "additionalProperties": False
}


def heuristic_report(m: Market) -> ResearchReport:
    # Neutral fallback: intentionally conservative; useful for plumbing tests, not alpha.
    p = min(0.95, max(0.05, m.yes_price))
    return ResearchReport(
        probability_yes=p, confidence=0.20,
        thesis="Fallback cuantitativo sin investigación externa.",
        counter_thesis="No existe una ventaja informativa demostrada.",
        risks=["OPENAI_API_KEY no configurada o IA desactivada"],
    )


def research_market(m: Market) -> ResearchReport:
    if not settings.ai_enabled or not settings.openai_api_key:
        return heuristic_report(m)
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = f"""
Actúa como analista escéptico de mercados predictivos. Investiga con fuentes web actuales.
Mercado: {m.question}
Reglas/descripción: {m.rules}
Precio YES: {m.yes_price:.4f}; precio NO: {m.no_price:.4f}
Fecha de cierre: {m.end_date}

Estima P(YES) usando solo información verificable disponible ahora. Evita anclarte al precio.
Incluye tesis, mejor argumento contrario, catalizadores, riesgos y URLs de fuentes.
Si la pregunta o resolución es ambigua, reduce confidence drásticamente.
"""
    response = client.responses.create(
        model=settings.openai_model,
        tools=[{"type": "web_search"}],
        input=prompt,
        text={"format": {"type": "json_schema", "name": "market_research", "strict": True, "schema": SCHEMA}},
    )
    return ResearchReport.model_validate(json.loads(response.output_text))
