import logging

from openai import OpenAI

from .config import settings
from .models import CriticReport, Market, ProbabilityReport

log = logging.getLogger(__name__)


def fallback(m: Market):
    p = ProbabilityReport(
        probability_yes=m.yes_price,
        confidence=0.15,
        thesis="No AI research configured",
        unknowns=["No independent evidence"],
    )
    c = CriticReport(
        risk_score=0.9,
        resolution_ambiguity=0.5,
        strongest_objection="No independent research",
        failure_modes=["Market-price anchoring"],
        recommendation="REJECT",
    )
    return p, c


def _client_and_model():
    provider = settings.ai_provider.strip().lower()
    if provider == "gemini":
        if not settings.gemini_api_key:
            return None, None
        return (
            OpenAI(
                api_key=settings.gemini_api_key,
                base_url=settings.gemini_base_url,
            ),
            settings.gemini_model,
        )
    if provider == "openai":
        if not settings.openai_api_key:
            return None, None
        return OpenAI(api_key=settings.openai_api_key), settings.openai_model
    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")


def _structured(client, model, prompt, response_model):
    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Return only the requested structured forecast. Be calibrated and conservative.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format=response_model,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("AI provider returned no structured result")
    return parsed


def research_market(m: Market):
    if not settings.ai_enabled:
        return fallback(m)

    client, model = _client_and_model()
    if client is None or model is None:
        return fallback(m)

    prompt = f"""You are an evidence-first prediction-market analyst. Estimate the probability that YES resolves true. Do not anchor on the market price. Distinguish event probability from resolution-rule risk.

QUESTION: {m.question}
RULES: {m.rules}
END: {m.end_date}
CATEGORY: {m.category}

Use only information you can support from your knowledge. Explicitly list unknowns and lower confidence when information may be stale, conflicting, speculative, or when the resolution wording is ambiguous."""
    p = _structured(client, model, prompt, ProbabilityReport)

    critic_prompt = f"""Act as an independent adversarial reviewer. Try to falsify this forecast and inspect resolution ambiguity.

MARKET: {m.question}
RULES: {m.rules}
FORECAST: {p.model_dump_json()}

Assign risk_score based on the chance the thesis is wrong or untradeable. REJECT when the argument depends on speculation, stale evidence, unclear rules, or fragile assumptions."""
    c = _structured(client, model, critic_prompt, CriticReport)
    return p, c
