import type { Settings } from "./config";
import type { EvidenceItem } from "./types";

const FORMULAIC_WORDS = new Set([
  "will", "would", "does", "do", "did", "is", "are", "be", "before", "after",
  "by", "on", "in", "of", "the", "a", "an", "this", "that", "market",
  "resolve", "resolves", "yes", "no",
]);

export function buildNewsQuery(question: string): string {
  const words = question.match(/[A-Za-z0-9][A-Za-z0-9'&.-]*/g) || [];
  const useful: string[] = [];
  for (const word of words) {
    const normalized = word.toLowerCase().replace(/^[.-]+|[.-]+$/g, "");
    if (FORMULAIC_WORDS.has(normalized)) continue;
    if (/^20\d{2}$/.test(normalized)) continue;
    useful.push(word);
  }
  const compact = useful.slice(0, 12).join(" ").trim();
  return compact ? `${compact} when:30d` : `"${question.trim()}" when:30d`;
}

function unescapeHtml(text: string): string {
  return text
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .trim();
}

function extractTag(block: string, tag: string): string {
  const match = block.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i"));
  return match ? unescapeHtml(match[1]) : "";
}

export async function currentEvidence(
  settings: Settings,
  question: string,
): Promise<EvidenceItem[]> {
  if (!settings.webResearchEnabled) return [];

  const query = buildNewsQuery(question);
  const url = new URL("https://news.google.com/rss/search");
  url.searchParams.set("q", query);
  url.searchParams.set("hl", "en-US");
  url.searchParams.set("gl", "US");
  url.searchParams.set("ceid", "US:en");

  try {
    const response = await fetch(url.toString(), {
      headers: { "User-Agent": "polymarket-alpha-engine-worker/1.1" },
      signal: AbortSignal.timeout(settings.webResearchTimeoutMs),
    });
    if (!response.ok) throw new Error(`Google News RSS request failed: ${response.status}`);
    const xml = await response.text();

    const items: EvidenceItem[] = [];
    const itemBlocks = xml.match(/<item>[\s\S]*?<\/item>/g) || [];
    for (const block of itemBlocks.slice(0, settings.webResearchMaxItems)) {
      const title = extractTag(block, "title");
      const link = extractTag(block, "link");
      const published = extractTag(block, "pubDate");
      const source = extractTag(block, "source");
      if (title) {
        items.push({ title, source, published, url: link, query });
      }
    }
    return items;
  } catch {
    return [];
  }
}

export function formatEvidence(items: EvidenceItem[]): string {
  if (items.length === 0) {
    return "No current web evidence could be retrieved. Treat the forecast as stale and lower confidence.";
  }
  return items
    .map((item, index) => `${index + 1}. ${item.title} | ${item.source} | ${item.published} | ${item.url}`)
    .join("\n");
}
