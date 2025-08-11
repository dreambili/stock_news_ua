# main.py
import os, time, html, hashlib, requests, feedparser
from fastapi import FastAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
RSS_URLS = [
    "https://finance.yahoo.com/rss/headline?s=%5EGSPC",  # S&P 500
    "https://finance.yahoo.com/rss/headline?s=%5EIXIC",  # Nasdaq
]
TRANSLATE_API_URL = os.getenv("TRANSLATE_API_URL", "https://translate.astian.org/translate")

app = FastAPI()
seen = set()  # простий дедуп до перезапуску

def h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()

def translate_uk(text: str) -> str:
    try:
        r = requests.post(
            TRANSLATE_API_URL, timeout=15,
            json={"q": text, "source": "en", "target": "uk", "format": "text"}
        )
        r.raise_for_status()
        return r.json().get("translatedText") or text
    except Exception:
        return text

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    r = requests.post(url, data=data, timeout=15)
    r.raise_for_status()

def fetch_and_post(limit_per_feed: int = 5) -> int:
    posted = 0
    for rss in RSS_URLS:
        feed = feedparser.parse(rss)
        for e in feed.entries[:limit_per_feed]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            key = h(link)
            if key in seen:
                continue
            ua = translate_uk(title)
            send_telegram(f"<b>{html.escape(ua)}</b>\n{html.escape(link)}")
            seen.add(key)
            posted += 1
            time.sleep(1)
    return posted

# Healthcheck (GET і HEAD)
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"ok": True}

# Тригер для публікацій (GET і HEAD)
@app.api_route("/run", methods=["GET", "HEAD"])
def run():
    try:
        n = fetch_and_post()
        return {"status": "ok", "posted": n}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
