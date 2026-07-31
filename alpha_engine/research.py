import logging

from openai import OpenAI

from .config import settings
from .evidence import current_evidence, format_evidence
from .models import CriticReport, Market, ProbabilityReport

log = logging.getLogger(__name__)


def fallback(m: Market):
    return (
        ProbabilityReport(probability_yes=m.yes_price, confidence=.15, thesis='No independent current evidence', unknowns=['Current evidence unavailable']),
        CriticReport(risk_score=.9, resolution_ambiguity=.5, strongest_objection='No current independent research', failure_modes=['Market-price anchoring'], recommendation='REJECT'),
    )


def _client_and_model():
    provider = settings.ai_provider.strip().lower()
    if provider == 'gemini':
        if not settings.gemini_api_key: return None, None
        return OpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url), settings.gemini_model
    if provider == 'openai':
        if not settings.openai_api_key: return None, None
        return OpenAI(api_key=settings.openai_api_key), settings.openai_model
    raise ValueError(f'Unsupported AI_PROVIDER: {settings.ai_provider}')


def _structured(client, model, prompt, response_model):
    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {'role': 'system', 'content': 'Return only the requested structured forecast. Use the supplied current evidence, distinguish publication time from event time, cite uncertainty, and remain calibrated.'},
            {'role': 'user', 'content': prompt},
        ],
        response_format=response_model,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError('AI provider returned no structured result')
    return parsed


def research_market(m: Market):
    if not settings.ai_enabled:
        return fallback(m)
    client, model = _client_and_model()
    if client is None or model is None:
        return fallback(m)

    evidence = current_evidence(m.question)
    evidence_text = format_evidence(evidence)
    prompt = f"""You are an evidence-first prediction-market analyst. Estimate the probability that YES resolves true. Do not anchor on the market price. Distinguish event probability from resolution-rule risk.

QUESTION: {m.question}
RULES: {m.rules}
END: {m.end_date}
CATEGORY: {m.category}

CURRENT WEB EVIDENCE:
{evidence_text}

Use the current evidence above. Do not invent article contents beyond their titles/source/time. Explicitly list missing facts and lower confidence when evidence is stale, conflicting, speculative, or insufficient. If no current evidence is available, confidence must be below {settings.min_confidence}."""
    probability = _structured(client, model, prompt, ProbabilityReport)

    critic_prompt = f"""Act as an independent adversarial reviewer. Falsify the forecast, inspect resolution ambiguity, and verify whether its claimed edge is supported by current evidence rather than memory.

MARKET: {m.question}
RULES: {m.rules}
CURRENT WEB EVIDENCE:
{evidence_text}
FORECAST: {probability.model_dump_json()}

REJECT when evidence is stale, weak, unrelated, contradictory, or insufficient for the confidence claimed."""
    critic = _structured(client, model, critic_prompt, CriticReport)
    return probability, critic
