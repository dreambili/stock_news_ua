import os, re, time, html, hashlib, requests, feedparser, sys
from urllib.parse import urlparse
from fastapi import FastAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")   # DeepL API Free, ключ закінчується на :fx
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

def deepl_translate(text: str) -> str:
    if not DEEPL_API_KEY:
        raise RuntimeError("DEEPL_API_KEY не задано")
    host = "api-free.deepl.com" if DEEPL_API_KEY.endswith(":fx") else "api.deepl.com"
    r = requests.post(f"https://{host}/v2/translate",
                      headers={"Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}"},
                      json={"text": [text], "source_lang": "EN", "target_lang": "UK"},
                      timeout=15)
    r.raise_for_status()
    return r.json()["translations"][0]["text"]

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

PROVIDERS = (("DeepL", deepl_translate),
             ("Google", google_translate),
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

# ---------- Формат поста як у "гарячих стрічках" ----------
# $TICKER - заголовок - Джерело 💎 #Компанії #Акції
# Підтвердили: Джерело2   (дописується редагуванням, коли ту ж новину дає інше джерело)

TICKERS = {  # ключове слово в англ. заголовку (lower) -> тікер
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "tesla": "TSLA",
    "amazon": "AMZN", "meta": "META", "facebook": "META", "alphabet": "GOOGL",
    "google": "GOOGL", "netflix": "NFLX", "amd": "AMD", "intel": "INTC",
    "broadcom": "AVGO", "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE",
    "palantir": "PLTR", "qualcomm": "QCOM", "micron": "MU", "tsmc": "TSM",
    "berkshire": "BRK.B", "jpmorgan": "JPM", "goldman": "GS", "morgan stanley": "MS",
    "bank of america": "BAC", "wells fargo": "WFC", "citigroup": "C", "visa": "V",
    "mastercard": "MA", "paypal": "PYPL", "coinbase": "COIN", "boeing": "BA",
    "walmart": "WMT", "costco": "COST", "target": "TGT", "nike": "NKE",
    "disney": "DIS", "starbucks": "SBUX", "mcdonald": "MCD", "coca-cola": "KO",
    "pepsico": "PEP", "exxon": "XOM", "chevron": "CVX", "pfizer": "PFE",
    "eli lilly": "LLY", "novo nordisk": "NVO", "unitedhealth": "UNH",
    "uber": "UBER", "airbnb": "ABNB", "shopify": "SHOP", "spotify": "SPOT",
    "alibaba": "BABA", "ford": "F", "general motors": "GM", "rivian": "RIVN",
    "microstrategy": "MSTR", "strategy inc": "MSTR", "super micro": "SMCI",
    "arm holdings": "ARM", "ibm": "IBM", "cisco": "CSCO", "dell": "DELL",
}
_TICKER_RE = [(re.compile(rf"\b{re.escape(k)}\b", re.I), v) for k, v in TICKERS.items()]
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b")

SOURCES = {  # домен -> назва джерела
    "reuters.com": "Reuters", "bloomberg.com": "Bloomberg", "cnbc.com": "CNBC",
    "wsj.com": "WSJ", "ft.com": "Financial Times", "marketwatch.com": "MarketWatch",
    "barrons.com": "Barron's", "investors.com": "IBD", "fool.com": "Motley Fool",
    "benzinga.com": "Benzinga", "seekingalpha.com": "Seeking Alpha",
    "zacks.com": "Zacks", "thestreet.com": "TheStreet", "businessinsider.com": "Business Insider",
    "forbes.com": "Forbes", "apnews.com": "AP", "finance.yahoo.com": "Yahoo Finance",
    "yahoo.com": "Yahoo Finance",
}

KEYWORD_TAGS = (  # (регекс по англ. заголовку, хештег)
    (r"\b(earnings|revenue|quarter|q[1-4]|guidance|eps)\b", "#Звіти"),
    (r"\b(fed|powell|rate cut|rate hike|inflation|cpi|jobs report|treasury)\b", "#Макро"),
    (r"\b(bitcoin|crypto|ether|ethereum)\b", "#Крипта"),
    (r"\b(oil|opec|crude|gold)\b", "#Сировина"),
    (r"\b(ipo)\b", "#IPO"),
)

def find_ticker(title_en: str):
    m = _CASHTAG_RE.search(title_en)
    if m: return m.group(1)
    for rx, t in _TICKER_RE:
        if rx.search(title_en): return t
    return None

def source_name(entry, link: str) -> str:
    src = entry.get("source")
    if isinstance(src, dict) and src.get("title"):
        return src["title"].strip()
    host = urlparse(link).netloc.lower().removeprefix("www.")
    for dom, name in SOURCES.items():
        if host == dom or host.endswith("." + dom):
            return name
    return host.split(".")[-2].capitalize() if host.count(".") >= 1 else "Джерело"

def hashtags(title_en: str, ticker) -> str:
    tags = ["#Компанії", "#Акції"] if ticker else ["#Ринок"]
    for rx, tag in KEYWORD_TAGS:
        if re.search(rx, title_en, re.I) and tag not in tags:
            tags.append(tag)
    return " ".join(tags)

def a(text: str, url: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'

def build_post(title_ua: str, ticker, src: str, link: str, tags: str, confirmed=()) -> str:
    head = f"${ticker} - {title_ua}" if ticker else title_ua
    text = f"<b>{html.escape(head)}</b> - {a(src, link)} 💎 {tags}"
    if confirmed:
        text += "\n\nПідтвердили: " + ", ".join(a(n, u) for n, u in confirmed)
    return text

# ---------- "Підтвердили": схожа новина від іншого джерела ----------
STOP = set("the a an of to in on for and or with as at by from is are be after over amid its it "
           "this that says said report reports stock stocks shares".split())
CONFIRM_WINDOW = 6 * 3600   # шукаємо дубль серед постів за останні 6 год
SIMILARITY = 0.5            # частка спільних слів у заголовках
recent = []                 # [{msg_id, words, ticker, src, ...}]

def words(title_en: str) -> set:
    return {w for w in re.findall(r"[a-z0-9$.]+", title_en.lower()) if w not in STOP and len(w) > 2}

def find_original(ws: set, ticker, src: str):
    now = time.time()
    recent[:] = [p for p in recent if now - p["ts"] < CONFIRM_WINDOW]
    for p in recent:
        if p["ticker"] != ticker or not ws or not p["words"]:
            continue
        if src == p["src"] or src in (n for n, _ in p["confirmed"]):
            continue
        if len(ws & p["words"]) / min(len(ws), len(p["words"])) >= SIMILARITY:
            return p
    return None

def tg(method: str, payload: dict) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()["result"]

def send_telegram(text: str) -> int:
    res = tg("sendMessage", {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML",
                             "link_preview_options": {"is_disabled": True}})
    return res["message_id"]

def edit_telegram(msg_id: int, text: str):
    tg("editMessageText", {"chat_id": CHANNEL_ID, "message_id": msg_id, "text": text,
                           "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}})

# ---------- Антиспам: публікуємо лише важливе ----------
MIN_SCORE = int(os.getenv("MIN_SCORE", "3"))                  # поріг важливості
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))  # максимум нових постів за один /run
MAX_AGE_HOURS = float(os.getenv("MAX_AGE_HOURS", "3"))        # старші новини ігноруються (і дублі після рестарту)
BLOCKED_SOURCES = {s.strip().lower() for s in
                   os.getenv("BLOCKED_SOURCES", "Motley Fool,Zacks,InvestorPlace,24/7 Wall St.,GuruFocus").split(",")}

HOT = re.compile(r"\b(surge[sd]?|soar(s|ed)?|plunge[sd]?|tumble[sd]?|crash(es|ed)?|sink(s)?|sank|skyrocket|"
                 r"record|all-time high|beats?|miss(es|ed)?|tops? estimates|guidance|outlook|"
                 r"acquir(e|es|ed|ition)|merger|buyout|takeover|deal to buy|stake|"
                 r"ceo|resign(s|ed)?|steps? down|fired|layoffs?|job cuts|"
                 r"lawsuit|sues?|probe|investigation|sec|doj|antitrust|fine[sd]?|ban(s|ned)?|tariffs?|"
                 r"fda|approv(al|es|ed)|recall|bankrupt(cy)?|default|"
                 r"upgrade[sd]?|downgrade[sd]?|price target|split|buyback|dividend cut|"
                 r"fed|powell|rate (cut|hike)|cpi|inflation|jobs report|payrolls|gdp|recession|"
                 r"halt(ed)?|breaking|exclusive)\b", re.I)
JUNK = re.compile(r"(\?|\bstocks? to (buy|watch|own)\b|\bshould you\b|\bhere'?s (why|what|how)\b|"
                  r"\bis it (time|too late)\b|\bbest\b|\btop \d+\b|^\d+ |\bmillionaire\b|\bprediction\b|"
                  r"\bcould\b|\bmight\b|\bwhat to (know|expect|watch)\b|\bmorning brief\b|\bpodcast\b|"
                  r"\bvideo\b|\bopinion\b|\bpassive income\b|\bretire(ment)?\b|\bbuy (now|and hold)\b|"
                  r"\bforever\b|\bno-brainer\b|\bbargain\b|\bsmartest\b)", re.I)
PCT = re.compile(r"\d+(\.\d+)?\s?%")

def score(title_en: str, ticker, src: str) -> int:
    if src.lower() in BLOCKED_SOURCES:
        return -99
    s = 0
    if ticker: s += 2
    s += 2 * min(len(HOT.findall(title_en)), 2)
    if PCT.search(title_en): s += 1
    if JUNK.search(title_en): s -= 4
    return s

def age_hours(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return (time.time() - time.mktime(t) + time.timezone) / 3600 if t else 0.0

def candidates(limit_per_feed: int):
    """Усі нові новини зі всіх стрічок з оцінкою, без дублів посилань."""
    out, links = [], set()
    for rss in RSS_URLS:
        for e in feedparser.parse(rss).entries[:limit_per_feed]:
            title, link = (e.get("title") or "").strip(), (e.get("link") or "").strip()
            if not title or not link or link in links: continue
            links.add(link)
            ticker, src_name = find_ticker(title), source_name(e, link)
            out.append({"e": e, "title": title, "link": link, "key": h(link), "ticker": ticker,
                        "src": src_name, "score": score(title, ticker, src_name), "age": age_hours(e)})
    return out

def fetch_and_post(limit_per_feed: int = 20) -> dict:
    posted = skipped = confirmed = filtered = 0
    fresh = []
    for c in candidates(limit_per_feed):
        if c["key"] in seen: continue
        if c["age"] > MAX_AGE_HOURS or c["score"] < MIN_SCORE:
            seen.add(c["key"]); filtered += 1          # нецікаве/старе — більше не розглядаємо
            continue
        fresh.append(c)
    fresh.sort(key=lambda c: (-c["score"], c["age"]))

    for c in fresh:
        try:
            ws = words(c["title"])
            orig = find_original(ws, c["ticker"], c["src"])
            if orig:  # та сама новина від іншого джерела -> "Підтвердили" (не рахується в ліміт)
                orig["confirmed"].append((c["src"], c["link"]))
                edit_telegram(orig["msg_id"], build_post(orig["ua"], orig["ticker"], orig["src"],
                                                         orig["link"], orig["tags"], orig["confirmed"]))
                seen.add(c["key"]); confirmed += 1; time.sleep(1)
                continue
            if posted >= MAX_POSTS_PER_RUN:
                continue                                # лишаємо на наступний /run, поки свіже
            ua = translate_uk(c["title"])
            if ua is None:
                if not POST_UNTRANSLATED:
                    skipped += 1
                    continue
                ua = c["title"]
            tags = hashtags(c["title"], c["ticker"])
            msg_id = send_telegram(build_post(ua, c["ticker"], c["src"], c["link"], tags))
            recent.append({"msg_id": msg_id, "ts": time.time(), "words": ws, "ticker": c["ticker"],
                           "src": c["src"], "link": c["link"], "ua": ua, "tags": tags, "confirmed": []})
            seen.add(c["key"]); posted += 1; time.sleep(1)
        except Exception as ex:
            log("post fail:", ex)
    log(f"posted {posted}, confirmed {confirmed}, filtered {filtered}, skipped (no translation) {skipped}")
    return {"posted": posted, "confirmed": confirmed, "filtered_out": filtered,
            "skipped_untranslated": skipped}

@app.api_route("/", methods=["GET", "HEAD"])
def root(): return {"ok": True}

@app.api_route("/test-translate", methods=["GET"])
def test_translate(q: str = "Microsoft shares rise on strong cloud growth"):
    report = []
    uk = translate_uk(q, report)
    return {"src": q, "uk": uk, "providers": report}

@app.api_route("/preview", methods=["GET"])
def preview(limit: int = 20):
    """Що пройде фільтр, а що ні (з оцінкою). Нічого не відправляє і не перекладає."""
    rows = []
    for c in sorted(candidates(limit), key=lambda c: -c["score"]):
        ok = c["score"] >= MIN_SCORE and c["age"] <= MAX_AGE_HOURS
        rows.append({"pass": ok, "score": c["score"], "age_h": round(c["age"], 1), "src": c["src"],
                     "post": build_post(c["title"], c["ticker"], c["src"], c["link"],
                                        hashtags(c["title"], c["ticker"]))})
    return {"min_score": MIN_SCORE, "max_posts_per_run": MAX_POSTS_PER_RUN,
            "max_age_hours": MAX_AGE_HOURS, "items": rows}

@app.api_route("/run", methods=["GET", "HEAD"])
def run():
    try:
        return {"status": "ok", **fetch_and_post()}
    except Exception as e:
        log("run error:", e)
        return {"status": "error", "detail": str(e)}
