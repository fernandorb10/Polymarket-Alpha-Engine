const CATEGORY_PATTERNS: Record<string, string[]> = {
  sports: [
    "nba", "nfl", "nhl", "mlb", "uefa", "champions league", "world cup",
    "premier league", "la liga", "serie a", "bundesliga", "tennis", "ufc",
    "formula 1", "super bowl", "playoffs", "ballon d'or", "football",
    "soccer", "basketball", "baseball", "hockey", "grand slam",
  ],
  crypto: [
    "bitcoin", "btc", "ethereum", "eth", "solana", "cryptocurrency",
    "crypto", "dogecoin", "xrp", "blockchain", "stablecoin",
  ],
  economy: [
    "fed", "federal reserve", "interest rate", "inflation", "gdp",
    "recession", "unemployment", "cpi", "stock market", "s&p", "nasdaq",
    "dow jones", "market cap", "largest company", "treasury yield",
  ],
  politics: [
    "election", "electoral", "president", "presidential", "prime minister",
    "senate", "congress", "nomination", "governor", "parliament", "mayor",
    "regime", "invade", "strike", "peace deal", "military clash",
    "popular vote", "electoral college",
  ],
  technology: [
    "artificial intelligence", "openai", "apple", "google", "alphabet",
    "microsoft", "tesla", "spacex", "iphone", "android", "ipo",
    "launch a token", "fdv",
  ],
  entertainment: [
    "oscar", "grammy", "emmy", "movie", "film", "album", "box office",
    "celebrity", "tv show", "streaming", "top grossing", "opening weekend",
  ],
};

const ALIASES: Record<string, string> = {
  sport: "sports",
  sports: "sports",
  crypto: "crypto",
  cryptocurrency: "crypto",
  economics: "economy",
  economy: "economy",
  finance: "economy",
  politics: "politics",
  political: "politics",
  technology: "technology",
  tech: "technology",
  entertainment: "entertainment",
  culture: "entertainment",
};

const STOPWORDS = new Set([
  "will", "does", "do", "is", "are", "the", "a", "an", "win", "wins",
  "winning", "be", "by", "on", "in", "of", "to", "as", "before", "after",
  "during", "reach", "have", "has",
]);

const US_STATES = new Set([
  "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
  "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
  "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
  "maine", "maryland", "massachusetts", "michigan", "minnesota",
  "mississippi", "missouri", "montana", "nebraska", "nevada", "hampshire",
  "jersey", "mexico", "york", "carolina", "dakota", "ohio", "oklahoma",
  "oregon", "pennsylvania", "rhode", "tennessee", "texas", "utah",
  "vermont", "virginia", "washington", "wisconsin", "wyoming",
]);

const EVENT_NOISE = new Set([
  ...US_STATES,
  "national", "state", "republican", "democratic", "democrat", "gop",
  "presidential", "president", "nomination", "nominee", "primary",
  "election", "electoral", "vote", "ballot",
]);

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function matches(text: string, pattern: string): boolean {
  const escaped = escapeRegExp(pattern).replace(/\\ /g, "\\s+");
  const re = new RegExp(`(?<![\\w])${escaped}(?![\\w])`, "i");
  return re.test(text);
}

export function classifyMarket(question: string, rawCategory = ""): string {
  const text = question.toLowerCase();
  for (const [category, patterns] of Object.entries(CATEGORY_PATTERNS)) {
    if (patterns.some((pattern) => matches(text, pattern))) return category;
  }

  const raw = ALIASES[(rawCategory || "").trim().toLowerCase()];
  if (raw) return raw;

  if (/\b(?:trump|biden|vance|rubio|harris|newsom|bolsonaro|le pen)\b/i.test(text)) {
    return "politics";
  }
  return "other";
}

function eventFamily(text: string, category: string): string {
  if (category === "politics") {
    if (/\b(?:win|carry|vote|ballot|electoral)\b/i.test(text)) return "election";
    if (/\b(?:nomination|nominee|primary)\b/i.test(text)) return "nomination";
    if (/\b(?:invade|strike|war|military|peace deal|regime)\b/i.test(text)) {
      return "geopolitics";
    }
  }
  if (category === "sports") {
    if (text.includes("ballon")) return "ballon-dor";
    return "competition";
  }
  if (category === "economy") {
    if (/\b(?:fed|interest rate|rate cut)\b/i.test(text)) return "fed-rates";
    if (text.includes("inflation") || text.includes("cpi")) return "inflation";
  }
  return category;
}

export function eventKey(question: string, rawCategory = ""): string {
  const category = classifyMarket(question, rawCategory);
  let text = question.toLowerCase();
  text = text.replace(
    /\b20\d{2}\b|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b/g,
    " ",
  );
  const words = (text.match(/[a-z][a-z'-]+/g) || []).filter(
    (word) => !STOPWORDS.has(word) && !EVENT_NOISE.has(word) && word.length > 2,
  );

  const uniqueWords: string[] = [];
  for (const word of words) {
    if (!uniqueWords.includes(word)) uniqueWords.push(word);
  }

  const family = eventFamily(text, category);
  const actorWords = uniqueWords.slice(0, 2);
  if (actorWords.length === 0) actorWords.push("unknown");
  return `${category}:${actorWords.join("-")}:${family}`.slice(0, 180);
}

export function classifyQuestion(question: string, rawCategory = ""): [string, string] {
  return [classifyMarket(question, rawCategory), eventKey(question, rawCategory)];
}
