import re


CATEGORY_PATTERNS = {
    'sports': (
        'nba', 'nfl', 'nhl', 'mlb', 'uefa', 'champions league', 'world cup',
        'premier league', 'la liga', 'serie a', 'bundesliga', 'tennis', 'ufc',
        'formula 1', 'super bowl', 'playoffs', 'ballon d', 'football', 'soccer',
        'basketball', 'baseball', 'hockey', 'grand slam',
    ),
    'crypto': (
        'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'cryptocurrency',
        'crypto', 'dogecoin', 'xrp', 'blockchain', 'stablecoin',
    ),
    'economy': (
        'fed ', 'federal reserve', 'interest rate', 'inflation', 'gdp',
        'recession', 'unemployment', 'cpi', 'stock market', 's&p', 'nasdaq',
        'dow jones', 'market cap', 'largest company', 'treasury yield',
    ),
    'politics': (
        'election', 'president', 'prime minister', 'senate', 'congress',
        'nomination', 'governor', 'parliament', 'mayor', 'regime', 'invade',
        'strike', 'peace deal', 'military clash',
    ),
    'technology': (
        'artificial intelligence', 'openai', 'apple', 'google', 'alphabet',
        'microsoft', 'tesla', 'spacex', 'iphone', 'android', ' ipo',
        'launch a token', 'fdv',
    ),
    'entertainment': (
        'oscar', 'grammy', 'emmy', 'movie', 'film', 'album', 'box office',
        'celebrity', 'tv show', 'streaming', 'top grossing', 'opening weekend',
    ),
}

ALIASES = {
    'sport': 'sports', 'sports': 'sports', 'crypto': 'crypto',
    'cryptocurrency': 'crypto', 'economics': 'economy', 'economy': 'economy',
    'finance': 'economy', 'politics': 'politics', 'political': 'politics',
    'technology': 'technology', 'tech': 'technology',
    'entertainment': 'entertainment', 'culture': 'entertainment',
}

STOPWORDS = {
    'will', 'does', 'do', 'is', 'are', 'the', 'a', 'an', 'win', 'be', 'by',
    'on', 'in', 'of', 'to', 'as', 'before', 'after', 'during', 'reach', 'have',
}


def classify_market(question: str, raw_category: str = '') -> str:
    text = f' {question.lower()} '
    for category, patterns in CATEGORY_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            return category
    return ALIASES.get((raw_category or '').strip().lower(), 'other')


def event_key(question: str, raw_category: str = '') -> str:
    """Build a stable correlation key from named entities and event family.

    It intentionally removes outcomes, dates and generic verbs so sibling markets such as
    Trump winning Pennsylvania/Georgia still share the same political actor family.
    """
    category = classify_market(question, raw_category)
    text = question.lower()
    text = re.sub(r'20\d{2}|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b', ' ', text)
    words = [w for w in re.findall(r"[a-z][a-z'-]+", text) if w not in STOPWORDS and len(w) > 2]

    # Preserve the leading subject/entity words and remove geography/outcome noise.
    noise = {'pennsylvania', 'georgia', 'florida', 'texas', 'california', 'national',
             'republican', 'democratic', 'presidential', 'nomination', 'election'}
    core = []
    for word in words:
        if word in noise:
            continue
        if word not in core:
            core.append(word)
        if len(core) >= 4:
            break
    return (category + ':' + '-'.join(core or words[:4] or ['unknown']))[:180]
