import os, time, html, hashlib, requests, feedparser
from fastapi import FastAPI
from deta import Deta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
RSS_URLS = [
    "http://finance.yahoo.com/rss/headline?s=%5EGSPC",
    "http://finance.yahoo.com/rss/headline?s=%5EIXIC"
]
TRANSLATE_API_URL = os.getenv("TRANSLATE_API_URL", "https://translate.astian.org/translate")

app = FastAPI()
deta = Deta()
db = deta.Base("seen_ids")

def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def translate_uk(text: str) -> str:
    try:
        r = requests.post(TRANSLATE_API_URL, timeout=15,
                          json={"q": text, "source": "en", "target": "uk", "format": "text"})
        r.raise_for_status()
        return r.json().get("translatedText") or text
    except:
        return text

def send_telegram(text: str):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
        timeout=15
    )

def post_new_items(limit=5):
    posted = 0
    for url in RSS_URLS:
        feed = feedparser.parse(url)
        for e in feed.entries[:limit]:
            title, link = e.get("title",""), e.get("link","")
            if not title or not link:
                continue
            key = _hash(link)
            if db.get(key):
                continue
            msg = f"<b>{html.escape(translate_uk(title))}</b>\n{html.escape(link)}"
            send_telegram(msg)
            db.put({"key": key})
            posted += 1
            time.sleep(1)
    return posted

@app.get("/")
def health():
    return {"ok": True}

@app.get("/run")
def run():
    try:
        n = post_new_items()
        return {"status": "ok", "posted": n}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
