import os, time, html, hashlib, requests, feedparser
from fastapi import FastAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
RSS_URLS = [
    "https://finance.yahoo.com/rss/headline?s=%5EGSPC",
    "https://finance.yahoo.com/rss/headline?s=%5EIXIC",
]
TRANSLATE_API_URL = os.getenv("TRANSLATE_API_URL", "https://translate.astian.org/translate")

app = FastAPI()
seen = set()  # простий дедуп між перезапусками

def h(s): import hashlib; return hashlib.sha1(s.encode()).hexdigest()

def translate_uk(text):
    try:
        r = requests.post(TRANSLATE_API_URL, timeout=15,
                          json={"q": text, "source": "en", "target": "uk", "format": "text"})
        r.raise_for_status()
        return r.json().get("translatedText") or text
    except:  # якщо впаде — відправляємо оригінал
        return text

def send_telegram(text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHANNEL_ID, "text": text, "parse_mode":"HTML"},
                  timeout=15).raise_for_status()

def fetch_and_post(limit=5):
    posted = 0
    for url in RSS_URLS:
        feed = feedparser.parse(url)
        for e in feed.entries[:limit]:
            title, link = e.get("title","").strip(), e.get("link","").strip()
            if not title or not link: continue
            key = h(link)
            if key in seen: continue
            ua = translate_uk(title)
            send_telegram(f"<b>{html.escape(ua)}</b>\n{html.escape(link)}")
            seen.add(key); posted += 1; time.sleep(1)
    return posted

@app.get("/")      # healthcheck
def root(): return {"ok": True}

@app.get("/run")   # UptimeRobot буде викликати це
def run():
    try:
        n = fetch_and_post()
        return {"status":"ok","posted":n}
    except Exception as e:
        return {"status":"error","detail":str(e)}
