import type { Settings } from "./config";
import { currentEvidence, formatEvidence } from "./evidence";
import type { CriticReport, EvidenceItem, Market, ProbabilityReport } from "./types";

const PROBABILITY_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    probability_yes: { type: "number", minimum: 0, maximum: 1 },
    confidence: { type: "number", minimum: 0, maximum: 1 },
    thesis: { type: "string" },
    evidence: { type: "array", items: { type: "string" } },
    counterarguments: { type: "array", items: { type: "string" } },
    unknowns: { type: "array", items: { type: "string" } },
    source_urls: { type: "array", items: { type: "string" } },
  },
  required: [
    "probability_yes",
    "confidence",
    "thesis",
    "evidence",
    "counterarguments",
    "unknowns",
    "source_urls",
  ],
};

const CRITIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    risk_score: { type: "number", minimum: 0, maximum: 1 },
    resolution_ambiguity: { type: "number", minimum: 0, maximum: 1 },
    strongest_objection: { type: "string" },
    failure_modes: { type: "array", items: { type: "string" } },
    recommendation: { type: "string", enum: ["ACCEPT", "REDUCE", "REJECT"] },
  },
  required: [
    "risk_score",
    "resolution_ambiguity",
    "strongest_objection",
    "failure_modes",
    "recommendation",
  ],
};

export function fallback(
  market: Market,
  reason = "No independent current evidence",
): [ProbabilityReport, CriticReport] {
  return [
    {
      probability_yes: market.yesPrice,
      confidence: 0,
      thesis: reason,
      evidence: [],
      counterarguments: [],
      unknowns: [reason],
      source_urls: [],
    },
    {
      risk_score: 1,
      resolution_ambiguity: 0.5,
      strongest_objection: reason,
      failure_modes: ["Insufficient independent evidence"],
      recommendation: "REJECT",
    },
  ];
}

function clientConfig(settings: Settings): { baseUrl: string; apiKey: string; model: string } | null {
  const provider = settings.aiProvider.trim().toLowerCase();
  if (provider === "gemini") {
    if (!settings.geminiApiKey) return null;
    return { baseUrl: settings.geminiBaseUrl, apiKey: settings.geminiApiKey, model: settings.geminiModel };
  }
  if (provider === "openai") {
    if (!settings.openaiApiKey) return null;
    return { baseUrl: "https://api.openai.com/v1/", apiKey: settings.openaiApiKey, model: settings.openaiModel };
  }
  throw new Error(`Unsupported AI_PROVIDER: ${settings.aiProvider}`);
}

async function structured<T>(
  config: { baseUrl: string; apiKey: string; model: string },
  settings: Settings,
  prompt: string,
  schemaName: string,
  schema: Record<string, unknown>,
): Promise<T> {
  const base = config.baseUrl.endsWith("/") ? config.baseUrl : `${config.baseUrl}/`;
  const response = await fetch(`${base}chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      model: config.model,
      messages: [
        {
          role: "system",
          content:
            "Return only the requested structured forecast. Use the supplied " +
            "current evidence, distinguish publication time from event time, " +
            "cite uncertainty, and remain calibrated.",
        },
        { role: "user", content: prompt },
      ],
      response_format: {
        type: "json_schema",
        json_schema: { name: schemaName, strict: true, schema },
      },
    }),
    signal: AbortSignal.timeout(settings.httpTimeoutMs),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`AI provider request failed: ${response.status} ${body.slice(0, 300)}`);
  }
  const data = (await response.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const content = data.choices?.[0]?.message?.content;
  if (!content) throw new Error("AI provider returned no structured result");
  return JSON.parse(content) as T;
}

function independentSourceCount(items: EvidenceItem[]): number {
  const sources = new Set(
    items.map((item) => item.source.trim().toLowerCase()).filter(Boolean),
  );
  return sources.size;
}

function attachEvidence(probability: ProbabilityReport, items: EvidenceItem[]): void {
  const urls = items.map((item) => item.url).filter(Boolean);
  probability.source_urls = Array.from(new Set([...probability.source_urls, ...urls]));

  const retrieved = items.map((item) => `WEB: ${item.title} | ${item.source} | ${item.published}`);
  probability.evidence = Array.from(new Set([...probability.evidence, ...retrieved]));

  if (items.length > 0 && items[0].query) {
    probability.unknowns = Array.from(
      new Set([...probability.unknowns, `News query used: ${items[0].query}`]),
    );
  }
}

export async function researchMarket(
  settings: Settings,
  market: Market,
): Promise<[ProbabilityReport, CriticReport]> {
  if (!settings.aiEnabled) return fallback(market, "AI disabled");

  const evidence = await currentEvidence(settings, market.question);
  const sourceCount = independentSourceCount(evidence);
  if (settings.requireWebEvidence && sourceCount < settings.minEvidenceSources) {
    return fallback(
      market,
      `Only ${sourceCount} independent current evidence sources; minimum is ${settings.minEvidenceSources}`,
    );
  }

  const config = clientConfig(settings);
  if (!config) return fallback(market, "AI provider unavailable");

  const evidenceText = formatEvidence(evidence);
  const prompt = `You are an evidence-first prediction-market analyst. Estimate the probability that YES resolves true. Do not anchor on the market price. Distinguish event probability from resolution-rule risk.

QUESTION: ${market.question}
RULES: ${market.rules}
END: ${market.endDate}
CATEGORY: ${market.category}

CURRENT WEB EVIDENCE:
${evidenceText}

Use only the current evidence above plus stable background knowledge. Do not invent article contents beyond their titles, source and publication time. Explicitly list missing facts and lower confidence when evidence is stale, conflicting, speculative, unrelated or insufficient. Calibrate confidence independently; no trading threshold is provided to you.`;

  const probability = await structured<ProbabilityReport>(
    config,
    settings,
    prompt,
    "probability_report",
    PROBABILITY_SCHEMA,
  );
  attachEvidence(probability, evidence);

  const criticPrompt = `Act as an independent adversarial reviewer. Falsify the forecast, inspect resolution ambiguity, and verify whether its claimed edge is supported by current evidence rather than memory.

MARKET: ${market.question}
RULES: ${market.rules}
CURRENT WEB EVIDENCE:
${evidenceText}
FORECAST: ${JSON.stringify(probability)}

REJECT when evidence is stale, weak, unrelated, contradictory, or insufficient for the confidence claimed. Do not infer article contents that are not present in the supplied evidence.`;

  const critic = await structured<CriticReport>(config, settings, criticPrompt, "critic_report", CRITIC_SCHEMA);
  return [probability, critic];
}
