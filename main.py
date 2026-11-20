import os, time, html, hashlib, requests, feedparser, sys
from fastapi import FastAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "")  # з email ліміт MyMemory 50 000 символів/день
LT_URL = os.getenv("TRANSLATE_API_URL", "")       # свій LibreTranslate, якщо є (публічний astian мертвий)
# 1 = публікувати англійською, якщо всі перекладачі впали; 0 = пропустити і спробувати на наступному /run
POST_UNTRANSLATED = os.getenv("POST_UNTRANSLATED", "0") == "1"

RSS_URLS = [
    "https://finance.yahoo.com/rss/headline?s=%5EGSPC",  # S&P 500
    "https://finance.yahoo.com/rss/headline?s=%5EIXIC",  # Nasdaq
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

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
        headers=UA, timeout=10,
    )
    r.raise_for_status()
    return "".join(part[0] for part in r.json()[0] if part and part[0])

def google2_translate(text: str) -> str:
    # запасний ендпоінт Google (інший ліміт / інший фронтенд)
    r = requests.get(
        "https://clients5.google.com/translate_a/t",
        params={"client": "dict-chrome-ex", "sl": "en", "tl": "uk", "q": text},
        headers=UA, timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    # формат: ["текст"] або [["текст","en"]]
    first = data[0] if isinstance(data, list) and data else ""
    return first[0] if isinstance(first, list) else str(first)

def mymemory_translate(text: str) -> str:
    params = {"q": text[:500], "langpair": "en|uk"}
    if MYMEMORY_EMAIL:
        params["de"] = MYMEMORY_EMAIL
    r = requests.get("https://api.mymemory.translated.net/get", params=params, headers=UA, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("responseStatus") not in (200, "200"):
        raise RuntimeError(data.get("responseDetails"))
    out = (data.get("responseData") or {}).get("translatedText") or ""
    if "MYMEMORY WARNING" in out.upper():
        raise RuntimeError(out)
    return out

def lt_translate(text: str) -> str:
    if not LT_URL:
        raise RuntimeError("TRANSLATE_API_URL не задано")
    # таймаут 70 с: free-інстанс Render прокидається до ~50 с
    r = requests.post(LT_URL, timeout=70,
                      json={"q": text, "source": "en", "target": "uk", "format": "text"})
    r.raise_for_status()
    return r.json().get("translatedText") or ""

PROVIDERS = (("Google", google_translate),
             ("Google2", google2_translate),
             ("MyMemory", mymemory_translate),
             ("LT", lt_translate))

def translate_uk(text: str, report=None):
    """Повертає переклад або None, якщо жоден сервіс не переклав."""
    for name, fn in PROVIDERS:
        try:
            t = fn(text)
            if _changed(text, t):
                if report is not None: report.append({name: "ok"})
                return t
            msg = "returned original"
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
        log(f"{name} fail:", msg)
        if report is not None: report.append({name: msg[:300]})
    return None

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    r = requests.post(url, data=data, timeout=15); r.raise_for_status()

def fetch_and_post(limit_per_feed: int = 5) -> dict:
    posted = skipped = 0
    for rss in RSS_URLS:
        feed = feedparser.parse(rss)
        for e in feed.entries[:limit_per_feed]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link: continue
            key = h(link)
            if key in seen: continue
            try:
                ua = translate_uk(title)
                if ua is None:
                    if not POST_UNTRANSLATED:
                        skipped += 1          # не додаємо в seen — спробуємо наступного разу
                        continue
                    ua = title
                text = f"<b>{html.escape(ua)}</b>\n{html.escape(link)}"
                send_telegram(text)
                seen.add(key); posted += 1; time.sleep(1)
            except Exception as ex:
                log("post fail:", ex)
    log(f"posted {posted}, skipped (no translation) {skipped}")
    return {"posted": posted, "skipped_untranslated": skipped}

@app.api_route("/", methods=["GET", "HEAD"])
def root(): return {"ok": True}

@app.api_route("/test-translate", methods=["GET"])
def test_translate(q: str = "Microsoft shares rise on strong cloud growth"):
    report = []
    uk = translate_uk(q, report)
    return {"src": q, "uk": uk, "providers": report}

@app.api_route("/run", methods=["GET", "HEAD"])
def run():
    try:
        return {"status": "ok", **fetch_and_post()}
    except Exception as e:
        log("run error:", e)
        return {"status": "error", "detail": str(e)}
