import json
import logging
from urllib import parse, request
from .config import settings

log = logging.getLogger(__name__)


def notify(message: str) -> bool:
    """Send a Telegram notification when credentials are configured."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = parse.urlencode({
        "chat_id": settings.telegram_chat_id,
        "text": message[:4000],
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = request.Request(url, data=payload, method="POST")
        with request.urlopen(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return bool(body.get("ok"))
    except Exception:
        log.exception("Telegram notification failed")
        return False
