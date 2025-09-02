import os, json, time, hashlib
from datetime import datetime, timezone
from typing import List, Dict
import feedparser
import requests
from flask import Flask, jsonify

# --- налаштування з ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # наприклад: @stock_news_ua або -100xxxxxxxxxx
TRANSLATE_API_URL = os.getenv("TRANSLATE_API_URL", "")  # напр.: https://translate.astian.org/translate

# Можеш змінити список фідів за бажанням:
DEFAULT_FEEDS = [
    # Три популярні потоки з фінансовими новинами
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^IXIC,^DJI&region=US&lang=en-US",
    "https://www.investing.com/rss/news_25.rss",     # General Finance
    "https://www.investing.com/rss/stock_Stock_Market.rss"
]

FEEDS = [x.strip() for x in os.getenv("SOURCE_FEEDS", ",".join(DEFAULT_FEEDS)).split(",") if x.strip()]

# файлики стану (зберігаються між рестартами під час одного аптайму інстансу)
LAST_RUN_FILE = "last_run.json"
POSTED_FILE = "posted_ids.json"

# --- Flask app ---
app = Flask(__name__)

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

def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def translate_to_uk(text: str) -> str:
    """Переклад через зовнішній API, якщо заданий. Інакше повертає оригінал."""
    if not TRANSLATE_API_URL or not text:
        return text
    try:
        resp = requests.post(
            TRANSLATE_API_URL,
            json={"q": text, "source": "en", "target": "uk", "format": "text"},
            timeout=12,
        )
        if resp.ok:
            data = resp.json()
            # Astian API повертає {"translatedText": "..."}
            return data.get("translatedText") or text
        return text
    except Exception:
        return text

def fetch_articles(feeds: List[str], max_items: int = 30) -> List[Dict]:
    """Забрати свіжі матеріали з кількох RSS і дедуплікувати за лінком/заголовком."""
    items: List[Dict] = []
    seen = set()
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries:
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                key = link or title
                if not key:
                    continue
                h = _hash(key)
                if h in seen:
                    continue
                seen.add(h)
                items.append({"title": title, "link": link})
        except Exception:
            continue
        if len(items) >= max_items:
            break
    return items

def send_to_telegram(text: str):
    if not BOT_TOKEN or not CHANNEL_ID:
        raise RuntimeError("BOT_TOKEN або CHANNEL_ID не вказані в ENV")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

def should_run_every_2h() -> bool:
    data = _load_json(LAST_RUN_FILE, {"last": 0})
    last = float(data.get("last", 0))
    return (_now_ts() - last) >= 2 * 60 * 60  # 2 години

def mark_ran_now():
    _save_json(LAST_RUN_FILE, {"last": _now_ts()})

def get_posted_set() -> set:
    data = _load_json(POSTED_FILE, {"ids": []})
    return set(data.get("ids", []))

def remember_posted(ids: List[str], keep: int = 300):
    s = list(get_posted_set())
    s.extend(ids)
    s = s[-keep:]
    _save_json(POSTED_FILE, {"ids": s})

def compose_message(item: Dict) -> str:
    title_uk = translate_to_uk(item["title"])
    link = item["link"]
    if link:
        return f"• <b>{title_uk}</b>\n{link}"
    return f"• <b>{title_uk}</b>"

@app.get("/")
def health():
    return jsonify({"ok": True})

@app.get("/run")
def run_job():
    # 1) стримінг частоти
    if not should_run_every_2h():
        return jsonify({"status": "skip", "reason": "posted less than 2h ago"})

    # 2) збір новин
    items = fetch_articles(FEEDS, max_items=50)
    posted_before = get_posted_set()

    to_post = []
    new_ids = []

    for it in items:
        key = _hash((it.get("link") or it.get("title") or "").strip())
        if key in posted_before:
            continue
        to_post.append(it)
        new_ids.append(key)
        if len(to_post) >= 3:   # рівно 3 шт за запуск
            break

    # 3) якщо нема нових — все одно оновлюємо "last run", щоб не молотити дарма
    if not to_post:
        mark_ran_now()
        return jsonify({"status": "ok", "posted": 0, "note": "no new items"})

    # 4) надсилаємо в канал
    sent = 0
    for it in to_post:
        try:
            send_to_telegram(compose_message(it))
            sent += 1
            time.sleep(0.7)  # невелика пауза, щоб не впиратись у rate limit
        except Exception:
            continue

    # 5) оновлюємо стан
    if sent:
        remember_posted(new_ids[:sent])
    mark_ran_now()

    return jsonify({"status": "ok", "posted": sent})
