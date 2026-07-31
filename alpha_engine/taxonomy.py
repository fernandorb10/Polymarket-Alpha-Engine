import re


CATEGORY_PATTERNS = {
    "sports": (
        "nba",
        "nfl",
        "nhl",
        "mlb",
        "uefa",
        "champions league",
        "world cup",
        "premier league",
        "la liga",
        "serie a",
        "bundesliga",
        "tennis",
        "ufc",
        "formula 1",
        "super bowl",
        "playoffs",
        "ballon d'or",
        "football",
        "soccer",
        "basketball",
        "baseball",
        "hockey",
        "grand slam",
    ),
    "crypto": (
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "solana",
        "cryptocurrency",
        "crypto",
        "dogecoin",
        "xrp",
        "blockchain",
        "stablecoin",
    ),
    "economy": (
        "fed",
        "federal reserve",
        "interest rate",
        "inflation",
        "gdp",
        "recession",
        "unemployment",
        "cpi",
        "stock market",
        "s&p",
        "nasdaq",
        "dow jones",
        "market cap",
        "largest company",
        "treasury yield",
    ),
    "politics": (
        "election",
        "electoral",
        "president",
        "presidential",
        "prime minister",
        "senate",
        "congress",
        "nomination",
        "governor",
        "parliament",
        "mayor",
        "regime",
        "invade",
        "strike",
        "peace deal",
        "military clash",
        "popular vote",
        "electoral college",
    ),
    "technology": (
        "artificial intelligence",
        "openai",
        "apple",
        "google",
        "alphabet",
        "microsoft",
        "tesla",
        "spacex",
        "iphone",
        "android",
        "ipo",
        "launch a token",
        "fdv",
    ),
    "entertainment": (
        "oscar",
        "grammy",
        "emmy",
        "movie",
        "film",
        "album",
        "box office",
        "celebrity",
        "tv show",
        "streaming",
        "top grossing",
        "opening weekend",
    ),
}

ALIASES = {
    "sport": "sports",
    "sports": "sports",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "economics": "economy",
    "economy": "economy",
    "finance": "economy",
    "politics": "politics",
    "political": "politics",
    "technology": "technology",
    "tech": "technology",
    "entertainment": "entertainment",
    "culture": "entertainment",
}

STOPWORDS = {
    "will",
    "does",
    "do",
    "is",
    "are",
    "the",
    "a",
    "an",
    "win",
    "wins",
    "winning",
    "be",
    "by",
    "on",
    "in",
    "of",
    "to",
    "as",
    "before",
    "after",
    "during",
    "reach",
    "have",
    "has",
}

US_STATES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "hampshire",
    "jersey",
    "mexico",
    "york",
    "carolina",
    "dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "wisconsin",
    "wyoming",
}

EVENT_NOISE = US_STATES | {
    "national",
    "state",
    "republican",
    "democratic",
    "democrat",
    "gop",
    "presidential",
    "president",
    "nomination",
    "nominee",
    "primary",
    "election",
    "electoral",
    "vote",
    "ballot",
}


def _matches(text: str, pattern: str) -> bool:
    """Match complete words or phrases, never accidental substrings."""
    escaped = re.escape(pattern).replace(r"\ ", r"\s+")
    return re.search(rf"(?<!\w){escaped}(?!\w)", text, flags=re.IGNORECASE) is not None


def classify_market(question: str, raw_category: str = "") -> str:
    text = question.casefold()
    for category, patterns in CATEGORY_PATTERNS.items():
        if any(_matches(text, pattern) for pattern in patterns):
            return category

    raw = ALIASES.get((raw_category or "").strip().casefold())
    if raw:
        return raw

    # Candidate-versus-geography markets often omit words such as "election".
    if re.search(r"\b(?:trump|biden|vance|rubio|harris|newsom|bolsonaro|le pen)\b", text):
        return "politics"
    return "other"


def _event_family(text: str, category: str) -> str:
    if category == "politics":
        if re.search(r"\b(?:win|carry|vote|ballot|electoral)\b", text):
            return "election"
        if re.search(r"\b(?:nomination|nominee|primary)\b", text):
            return "nomination"
        if re.search(r"\b(?:invade|strike|war|military|peace deal|regime)\b", text):
            return "geopolitics"
    if category == "sports":
        if "ballon" in text:
            return "ballon-dor"
        return "competition"
    if category == "economy":
        if re.search(r"\b(?:fed|interest rate|rate cut)\b", text):
            return "fed-rates"
        if "inflation" in text or "cpi" in text:
            return "inflation"
    return category


def event_key(question: str, raw_category: str = "") -> str:
    """Build a conservative correlation key from actor and event family.

    Geography, dates and outcome wording are deliberately removed so sibling
    markets tied to the same actor and event family share a portfolio limit.
    """
    category = classify_market(question, raw_category)
    text = question.casefold()
    text = re.sub(
        r"\b20\d{2}\b|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",
        " ",
        text,
    )
    words = [
        word
        for word in re.findall(r"[a-z][a-z'-]+", text)
        if word not in STOPWORDS and word not in EVENT_NOISE and len(word) > 2
    ]

    unique_words = []
    for word in words:
        if word not in unique_words:
            unique_words.append(word)

    family = _event_family(text, category)
    actor_words = unique_words[:2]
    if not actor_words:
        actor_words = ["unknown"]
    return f"{category}:{'-'.join(actor_words)}:{family}"[:180]
