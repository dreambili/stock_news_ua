import os, json, time, hashlib
from datetime import datetime, timezone
from typing import List, Dict

import feedparser
import requests
from flask import Flask, jsonify

# ============ ENV ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()  # @channel або -100xxxxxxxxxx
ENV_TRANSLATE = os.getenv("TRANSLATE_API_URL", "").strip()  # напр.: https://translate.argosopentech.com/translate

DEFAULT_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^IXIC,^DJI&region=US&lang=en-US",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/stock_Stock_Market.rss",
]
FEEDS = [x.strip() for x in os.getenv("SOURCE_FEEDS", ",".join(DEFAULT_FEEDS)).split(",") if x.strip()]

# ============ STATE FILES ============
LAST_RUN_FILE = "last_run.json"
POSTED_FILE = "posted_ids.json"

# ============ APP ============
app = Flask(__name__)

# ============ HELPERS ============
def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def _hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def should_run_every_2h() -> bool:
    last = float(_load_json(LAST_RUN_FILE, {"last": 0}).get("last", 0))
    return (_now_ts() - last) >= 2 * 60 * 60

def mark_ran_now():
    _save_json(LAST_RUN_FILE, {"last": _now_ts()})

def get_posted_set() -> set:
    return set(_load_json(POSTED_FILE, {"ids": []}).get("ids", []))

def remember_posted(ids: List[str], keep: int = 800):
    s = list(get_posted_set())
    s.extend(ids)
    s = s[-keep:]
    _save_json(POSTED_FILE, {"ids": s})

# ============ TRANSLATION (EN -> UK) ============
def _translate_call(url: str, text: str) -> str | None:
    """Виклик LibreTranslate-сумісного API. Повертає переклад або None."""
    try:
        r = requests.post(
            url,
            json={"q": text, "source": "en", "target": "uk", "format": "text"},
            timeout=12,
            headers={"Accept": "application/json", "User-Agent": "stock_news_ua/1.0"},
        )
        if r.ok:
            try:
                j = r.json()
            except Exception:
                print(f"[WARN] translate API {url} non-JSON: {r.text[:160]}")
                return None
            t = j.get("translatedText")
            if isinstance(t, str) and t.strip():
                return t
            print(f"[WARN] translate API {url} empty translatedText")
        else:
            print(f"[WARN] translate API {url} -> {r.status_code}: {r.text[:160]}")
    except Exception as e:
        print(f"[ERROR] translate API {url} failed: {e}")
    return None

# порядок спроб: ENV → Argos → LibreTranslate.de → Astian
TRANSLATE_ENDPOINTS = [e for e in [
    ENV_TRANSLATE or None,
    "https://translate.argosopentech.com/translate",
    "https://libretranslate.de/translate",
    "https://translate.astian.org/translate",
] if e]

def translate_to_uk(text: str) -> str:
    if not text:
        return text
    for ep in TRANSLATE_ENDPOINTS:
        res = _translate_call(ep, text)
        if res:
            return res
    return text  # якщо все впало — повертаємо оригінал

# ============ RSS ============
def fetch_articles(feeds: List[str], limit: int = 120) -> List[Dict]:
    items, seen = [], set()
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries:
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                key_src = link or title
                if not key_src:
                    continue
                key = _hash(key_src)
                if key in seen:
                    continue
                seen.add(key)
                items.append({"title": title, "link": link, "key": key})
        except Exception as e:
            print(f"[WARN] RSS parse failed for {url}: {e}")
            continue
        if len(items) >= limit:
            break
    return items

# ============ TELEGRAM ============
def send_to_telegram(text: str):
    if not BOT_TOKEN or not CHANNEL_ID:
        raise RuntimeError("BOT_TOKEN або CHANNEL_ID не задані в Environment")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,  # увімкнене прев'ю картки
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

def compose_message(item: Dict) -> str:
    title_uk = translate_to_uk(item["title"])
    link = item["link"]
    return f"{title_uk}\n{link}" if link else title_uk

# ============ ROUTES ============
@app.get("/")
def health():
    return jsonify({"ok": True})

@app.get("/diag")
def diag():
    return jsonify({
        "feeds": FEEDS,
        "translate_endpoints": TRANSLATE_ENDPOINTS,
        "has_bot": bool(BOT_TOKEN),
        "has_channel": bool(CHANNEL_ID),
        "last_run": _load_json(LAST_RUN_FILE, {"last": 0}).get("last", 0),
        "posted_count": len(get_posted_set()),
    })

@app.get("/run")
def run_job():
    # 1) частота
    if not should_run_every_2h():
        return jsonify({"status": "skip", "reason": "less than 2h since last run"})

    # 2) збір новин
    items = fetch_articles(FEEDS, limit=120)
    posted = get_posted_set()

    to_post, new_ids = [], []
    for it in items:
        if it["key"] in posted:
            continue
        to_post.append(it)
        new_ids.append(it["key"])
        if len(to_post) == 3:  # рівно 3 за запуск
            break

    if not to_post:
        mark_ran_now()
        return jsonify({"status": "ok", "posted": 0, "note": "no new items"})

    # 3) відправка
    sent = 0
    for it in to_post:
        try:
            send_to_telegram(compose_message(it))
            sent += 1
            time.sleep(0.7)
        except Exception as e:
            print(f"[ERROR] telegram send failed: {e}")

    # 4) стан
    if sent:
        remember_posted(new_ids[:sent])
    mark_ran_now()

    return jsonify({"status": "ok", "posted": sent})
