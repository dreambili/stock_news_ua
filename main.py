import os, time, html, hashlib, requests, feedparser, sys
from fastapi import FastAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "")  # з email ліміт MyMemory 50 000 символів/день

RSS_URLS = [
    "https://finance.yahoo.com/rss/headline?s=%5EGSPC",  # S&P 500
    "https://finance.yahoo.com/rss/headline?s=%5EIXIC",  # Nasdaq
]

LT_URL = os.getenv("TRANSLATE_API_URL", "https://translate.astian.org/translate")

app = FastAPI()
seen = set()

def log(*a): print(*a, file=sys.stdout, flush=True)
def h(s: str) -> str: return hashlib.sha1(s.encode()).hexdigest()

def _changed(src: str, out: str) -> bool:
    return bool(out) and out.strip().lower() != src.strip().lower()

def google_translate(text: str) -> str:
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "en", "tl": "uk", "dt": "t", "q": text},
        timeout=10,
    )
    r.raise_for_status()
    return "".join(part[0] for part in r.json()[0] if part and part[0])

def mymemory_translate(text: str) -> str:
    params = {"q": text[:500], "langpair": "en|uk"}
    if MYMEMORY_EMAIL:
        params["de"] = MYMEMORY_EMAIL
    r = requests.get("https://api.mymemory.translated.net/get", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("responseStatus") not in (200, "200"):
        raise RuntimeError(data.get("responseDetails"))
    return (data.get("responseData") or {}).get("translatedText") or ""

def lt_translate(text: str) -> str:
    # таймаут 70 с: free-інстанс Render прокидається до ~50 с
    r = requests.post(LT_URL, timeout=70,
        json={"q": text, "source": "en", "target": "uk", "format": "text"})
    r.raise_for_status()
    return r.json().get("translatedText") or ""

def translate_uk(text: str) -> str:
    for name, fn in (("Google", google_translate),
                     ("MyMemory", mymemory_translate),
                     ("LT", lt_translate)):
        try:
            t = fn(text)
            if _changed(text, t):
                return t
            log(f"{name} returned original")
        except Exception as e:
            log(f"{name} fail:", e)
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
            try:
                ua = translate_uk(title)
                text = f"<b>{html.escape(ua)}</b>\n{html.escape(link)}"
                send_telegram(text)
                seen.add(key); posted += 1; time.sleep(1)
            except Exception as ex:
                log("post fail:", ex)
    log(f"posted {posted} items"); return posted

@app.api_route("/", methods=["GET","HEAD"])
def root(): return {"ok": True}

@app.api_route("/test-translate", methods=["GET"])
def test_translate(q: str = "Microsoft shares rise on strong cloud growth"):
    return {"src": q, "uk": translate_uk(q)}

@app.api_route("/run", methods=["GET","HEAD"])
def run():
    try:
        n = fetch_and_post()
        return {"status":"ok","posted":n}
    except Exception as e:
        log("run error:", e)
        return {"status":"error","detail":str(e)}
