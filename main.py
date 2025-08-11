import os, time, html, hashlib, requests, feedparser, sys
from fastapi import FastAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

RSS_URLS = [
    "https://finance.yahoo.com/rss/headline?s=%5EGSPC",  # S&P 500
    "https://finance.yahoo.com/rss/headline?s=%5EIXIC",  # Nasdaq
]

LT_URL = os.getenv("TRANSLATE_API_URL", "https://translate.astian.org/translate")

app = FastAPI()
seen = set()

def log(*a): print(*a, file=sys.stdout, flush=True)
def h(s: str) -> str: return hashlib.sha1(s.encode()).hexdigest()

def lt_translate(text: str) -> str:
    r = requests.post(LT_URL, timeout=12,
        json={"q": text, "source": "en", "target": "uk", "format": "text"})
    r.raise_for_status()
    return r.json().get("translatedText") or text

def mymemory_translate(text: str) -> str:
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": "en|uk"},
        timeout=10
    )
    r.raise_for_status()
    data = r.json()
    return (data.get("responseData") or {}).get("translatedText") or text

def translate_uk(text: str) -> str:
    try:
        t = lt_translate(text)
        if t and t.strip().lower() != text.strip().lower():
            return t
        # якщо LibreTranslate повернув оригінал, пробуємо fallback
        raise RuntimeError("LT returned original")
    except Exception as e:
        log("LT fail:", e)
        try:
            t2 = mymemory_translate(text)
            return t2 or text
        except Exception as e2:
            log("MyMemory fail:", e2)
            return text

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    r = requests.post(url, data=data, timeout=15); r.raise_for_status()

def fetch_and_post(limit_per_feed: int = 5) -> int:
    posted = 0
    for rss in RSS_URLS:
        feed = feedparser.parse(rss)
        for e in feed.entries[:limit_per_feed]:
            title = (e.get("title") or "").strip()
            link  = (e.get("link")  or "").strip()
            if not title or not link: continue
            key = h(link)
            if key in seen: continue
            ua = translate_uk(title)
            text = f"<b>{html.escape(ua)}</b>\n{html.escape(link)}"
            send_telegram(text)
            seen.add(key); posted += 1; time.sleep(1)
    log(f"posted {posted} items"); return posted

@app.api_route("/", methods=["GET","HEAD"])
def root(): return {"ok": True}

@app.api_route("/run", methods=["GET","HEAD"])
def run():
    try:
        n = fetch_and_post()
        return {"status":"ok","posted":n}
    except Exception as e:
        log("run error:", e)
        return {"status":"error","detail":str(e)}
