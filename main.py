import os, json, time, hashlib
from datetime import datetime, timezone
from typing import List, Dict

import feedparser
import requests
from flask import Flask, jsonify

# ====== НАЛАШТУВАННЯ ЧЕРЕЗ ENV ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()  # @your_channel або -100XXXXXXXXXX
TRANSLATE_API_URL = os.getenv("TRANSLATE_API_URL", "").strip()  # наприклад: https://translate.astian.org/translate

DEFAULT_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^IXIC,^DJI&region=US&lang=en-US",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/stock_Stock_Market.rss",
]
FEEDS = [x.strip() for x in os.getenv("SOURCE_FEEDS", ",".join(DEFAULT_FEEDS)).split(",") if x.strip()]

# Файли локального стану (переживають “сон” інстансу, але не redeploy)
LAST_RUN_FILE = "last_run.json"
POSTED_FILE = "posted_ids.json"

app = Flask(__name__)

# ====== ХЕЛПЕРИ ======
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
    return (_now_ts() - last) >= 2 * 60 * 60  # 2 години

def mark_ran_now():
    _save_json(LAST_RUN_FILE, {"last": _now_ts()})

def get_posted_set() -> set:
    return set(_load_json(POSTED_FILE, {"ids": []}).get("ids", []))

def remember_posted(ids: List[str], keep: int = 500):
    s = list(get_posted_set())
    s.extend(ids)
    s = s[-keep:]
    _save_json(POSTED_FILE, {"ids": s})

def translate_to_uk(text: str) -> str:
    """Опційний переклад через TRANSLATE_API_URL (Astian або сумісний)."""
    if not TRANSLATE_API_URL or not text:
        return text
    try:
        r = requests.post(
            TRANSLATE_API_URL,
            json={"q": text, "source": "en", "target": "uk", "format": "text"},
            timeout=12,
        )
        if r.ok:
            j = r.json()
            return j.get("translatedText") or text
    except Exception:
        pass
    return text

def fetch_articles(feeds: List[str], limit: int = 60) -> List[Dict]:
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
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items

def send_to_telegram(text: str):
    if not BOT_TOKEN or not CHANNEL_ID:
        raise RuntimeError("BOT_TOKEN або CHANNEL_ID не задані")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

def compose_message(item: Dict) -> str:
    title_uk = translate_to_uk(item["title"])
    if item["link"]:
        return f"• <b>{title_uk}</b>\n{item['link']}"
    return f"• <b>{title_uk}</b>"

# ====== РОУТИ ======
@app.get("/")
def health():
    return jsonify({"ok": True})

@app.get("/run")
def run_job():
    # 1) Ліміт частоти
    if not should_run_every_2h():
        return jsonify({"status": "skip", "reason": "less than 2h since last run"})

    # 2) Збір і фільтр новин
    items = fetch_articles(FEEDS, limit=80)
    posted = get_posted_set()

    to_post, new_ids = [], []
    for it in items:
        if it["key"] in posted:
            continue
        to_post.append(it)
        new_ids.append(it["key"])
        if len(to_post) == 3:   # рівно 3 за запуск
            break

    # 3) Якщо немає нових — просто оновлюємо мітку, щоб не молотити кожні 5 хв
    if not to_post:
        mark_ran_now()
        return jsonify({"status": "ok", "posted": 0, "note": "no new items"})

    # 4) Відправка
    sent = 0
    for it in to_post:
        try:
            send_to_telegram(compose_message(it))
            sent += 1
            time.sleep(0.7)
        except Exception:
            pass

    # 5) Зберігаємо стан та мітку часу
    if sent:
        remember_posted(new_ids[:sent])
    mark_ran_now()

    return jsonify({"status": "ok", "posted": sent})
