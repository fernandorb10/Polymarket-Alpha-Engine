import json, logging
from openai import OpenAI
from .config import settings
from .models import Market, ProbabilityReport, CriticReport
log=logging.getLogger(__name__)

PROB_SCHEMA={"type":"object","properties":{"probability_yes":{"type":"number","minimum":0,"maximum":1},"confidence":{"type":"number","minimum":0,"maximum":1},"thesis":{"type":"string"},"evidence":{"type":"array","items":{"type":"string"}},"counterarguments":{"type":"array","items":{"type":"string"}},"unknowns":{"type":"array","items":{"type":"string"}},"source_urls":{"type":"array","items":{"type":"string"}}},"required":["probability_yes","confidence","thesis","evidence","counterarguments","unknowns","source_urls"],"additionalProperties":False}
CRITIC_SCHEMA={"type":"object","properties":{"risk_score":{"type":"number","minimum":0,"maximum":1},"resolution_ambiguity":{"type":"number","minimum":0,"maximum":1},"strongest_objection":{"type":"string"},"failure_modes":{"type":"array","items":{"type":"string"}},"recommendation":{"type":"string","enum":["ACCEPT","REDUCE","REJECT"]}},"required":["risk_score","resolution_ambiguity","strongest_objection","failure_modes","recommendation"],"additionalProperties":False}

def fallback(m: Market):
    p=ProbabilityReport(probability_yes=m.yes_price,confidence=.15,thesis="No AI research configured",unknowns=["No independent evidence"])
    c=CriticReport(risk_score=.9,resolution_ambiguity=.5,strongest_objection="No independent research",failure_modes=["Market-price anchoring"],recommendation="REJECT")
    return p,c

def _structured(client, prompt, name, schema, web=False):
    kwargs={"model":settings.openai_model,"input":prompt,"text":{"format":{"type":"json_schema","name":name,"strict":True,"schema":schema}}}
    if web: kwargs["tools"]=[{"type":"web_search"}]
    response=client.responses.create(**kwargs)
    return json.loads(response.output_text)

def research_market(m: Market):
    if not settings.ai_enabled or not settings.openai_api_key: return fallback(m)
    client=OpenAI(api_key=settings.openai_api_key)
    prompt=f"""You are an evidence-first prediction-market analyst. Research current, verifiable information and estimate the probability that YES resolves true. Do not anchor on the market price. Distinguish event probability from resolution-rule risk.
QUESTION: {m.question}
RULES: {m.rules}
END: {m.end_date}
CATEGORY: {m.category}
Return calibrated probabilities; lower confidence when evidence is weak, stale, conflicting, or the resolution wording is ambiguous."""
    p=ProbabilityReport.model_validate(_structured(client,prompt,"probability_report",PROB_SCHEMA,True))
    critic_prompt=f"""Act as an independent adversarial reviewer. Try to falsify this forecast and inspect resolution ambiguity.
MARKET: {m.question}
RULES: {m.rules}
FORECAST: {p.model_dump_json()}
Assign risk_score based on the chance the thesis is wrong or untradeable. REJECT when the argument depends on speculation, stale evidence, unclear rules, or fragile assumptions."""
    c=CriticReport.model_validate(_structured(client,critic_prompt,"critic_report",CRITIC_SCHEMA,False))
    return p,c
