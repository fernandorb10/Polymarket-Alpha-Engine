import logging

from openai import OpenAI

from .config import settings
from .evidence import current_evidence, format_evidence
from .models import CriticReport, Market, ProbabilityReport

log = logging.getLogger(__name__)


def fallback(market: Market, reason: str = "Current evidence unavailable"):
    return (
        ProbabilityReport(
            probability_yes=market.yes_price,
            confidence=0.0,
            thesis="No trade: independent current evidence is unavailable",
            unknowns=[reason],
        ),
        CriticReport(
            risk_score=1.0,
            resolution_ambiguity=0.5,
            strongest_objection=reason,
            failure_modes=["No auditable current evidence"],
            recommendation="REJECT",
        ),
    )


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
                "content": (
                    "Return only the requested structured forecast. Use the supplied "
                    "current evidence, distinguish publication time from event time, "
                    "cite uncertainty, and remain calibrated."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format=response_model,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("AI provider returned no structured result")
    return parsed


def _attach_evidence(probability: ProbabilityReport, items: list[dict[str, str]]) -> None:
    urls = [item["url"] for item in items if item.get("url")]
    probability.source_urls = list(dict.fromkeys([*probability.source_urls, *urls]))

    retrieved = [
        f"WEB: {item['title']} | {item['source']} | {item['published']}"
        for item in items
    ]
    probability.evidence = list(dict.fromkeys([*probability.evidence, *retrieved]))

    if items:
        query = items[0].get("query")
        if query:
            probability.unknowns = list(
                dict.fromkeys([*probability.unknowns, f"News query used: {query}"])
            )


def research_market(market: Market):
    if not settings.ai_enabled:
        return fallback(market, "AI research is disabled")

    evidence = current_evidence(market.question)
    if settings.require_web_evidence and not evidence:
        return fallback(market, "No current web evidence was retrieved")

    client, model = _client_and_model()
    if client is None or model is None:
        return fallback(market, "AI provider is not configured")

    evidence_text = format_evidence(evidence)
    prompt = f"""You are an evidence-first prediction-market analyst. Estimate the probability that YES resolves true. Do not anchor on the market price. Distinguish event probability from resolution-rule risk.

QUESTION: {market.question}
RULES: {market.rules}
END: {market.end_date}
CATEGORY: {market.category}

CURRENT WEB EVIDENCE:
{evidence_text}

Use only the current evidence above plus stable background knowledge. Do not invent article contents beyond their titles, source and publication time. Explicitly list missing facts and lower confidence when evidence is stale, conflicting, speculative, unrelated or insufficient. Calibrate confidence independently; no trading threshold is provided to you."""
    probability = _structured(client, model, prompt, ProbabilityReport)
    _attach_evidence(probability, evidence)

    critic_prompt = f"""Act as an independent adversarial reviewer. Falsify the forecast, inspect resolution ambiguity, and verify whether its claimed edge is supported by current evidence rather than memory.

MARKET: {market.question}
RULES: {market.rules}
CURRENT WEB EVIDENCE:
{evidence_text}
FORECAST: {probability.model_dump_json()}

REJECT when evidence is stale, weak, unrelated, contradictory, or insufficient for the confidence claimed. Do not infer article contents that are not present in the supplied evidence."""
    critic = _structured(client, model, critic_prompt, CriticReport)
    return probability, critic
