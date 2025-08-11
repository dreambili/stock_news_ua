import os, time, html, json, requests, feedparser, sys
from telegram import Bot, constants

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # @назва_каналу або числовий ID
INTERVAL_MIN = int(os.getenv("INTERVAL_MIN", "30"))

# RSS Yahoo Finance для S&P 500 і Nasdaq (можеш змінити)
RSS_URLS = [
    "https://finance.yahoo.com/rss/headline?s=%5EGSPC",
    "https://finance.yahoo.com/rss/headline?s=%5EIXIC",
]

TRANSLATE_API_URL = os.getenv("TRANSLATE_API_URL", "https://translate.astian.org/translate")
SEEN_PATH = "seen_ids.json"  # локальний файл для дедуплікації

bot = Bot(BOT_TOKEN)

def log(*a): print(*a, file=sys.stdout, flush=True)

def load_seen():
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()

def save_seen(seen):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen)), f)

def translate_uk(text: str) -> str:
    try:
        r = requests.post(
            TRANSLATE_API_URL, timeout=15,
            json={"q": text, "source": "en", "target": "uk", "format": "text"}
        )
        r.raise_for_status()
        return r.json().get("translatedText") or text
    except Exception as e:
        log("translate error:", e)
        return text

def post_message(title_en: str, link: str):
    title_uk = translate_uk(title_en)
    text = f"<b>{html.escape(title_uk)}</b>\n{html.escape(link)}"
    bot.send_message(
        chat_id=CHANNEL_ID,
        text=text,
        parse_mode=constants.ParseMode.HTML,
        disable_web_page_preview=False
    )

def fetch_and_post():
    seen = load_seen()
    posted = 0
    for rss in RSS_URLS:
        feed = feedparser.parse(rss)
        for e in feed.entries:
            title = e.get("title", "").strip()
            link = e.get("link", "").strip()
            if not title or not link:
                continue
            key = link  # достатньо унікально
            if key in seen:
                continue
            post_message(title, link)
            seen.add(key); save_seen(seen)
            posted += 1
            time.sleep(1)
    log(f"posted {posted} items")

if __name__ == "__main__":
    log("worker started")
    while True:
        try:
            fetch_and_post()
        except Exception as e:
            log("cycle error:", e)
        time.sleep(INTERVAL_MIN * 60)
