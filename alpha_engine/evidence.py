import html
import logging
import urllib.parse
import xml.etree.ElementTree as ET

import httpx

from .config import settings

log = logging.getLogger(__name__)


def current_evidence(query: str) -> list[dict[str, str]]:
    """Fetch current Google News RSS evidence without requiring another API key."""
    if not settings.web_research_enabled:
        return []
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({
        'q': query,
        'hl': 'en-US',
        'gl': 'US',
        'ceid': 'US:en',
    })
    try:
        response = httpx.get(url, timeout=settings.web_research_timeout, follow_redirects=True,
                             headers={'User-Agent': 'polymarket-alpha-engine/1.1'})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for item in root.findall('.//item')[:settings.web_research_max_items]:
            title = html.unescape(item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            published = (item.findtext('pubDate') or '').strip()
            source = item.find('source')
            source_name = source.text.strip() if source is not None and source.text else ''
            if title:
                items.append({'title': title, 'source': source_name, 'published': published, 'url': link})
        return items
    except Exception as exc:
        log.warning('web evidence unavailable for %r: %s', query, exc)
        return []


def format_evidence(items: list[dict[str, str]]) -> str:
    if not items:
        return 'No current web evidence could be retrieved. Treat the forecast as stale and lower confidence.'
    lines = []
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {item['title']} | {item['source']} | {item['published']} | {item['url']}")
    return '\n'.join(lines)
