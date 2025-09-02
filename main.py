import os
import sys
import time
import json
import logging
import threading

import feedparser
import telebot
from flask import Flask
from googletrans import Translator

# =========================
#        НАЛАШТУВАННЯ
# =========================
# ⚠️ Токен беремо зі змінної середовища (Render → Settings → Environment)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("[FATAL] Не задано змінну середовища BOT_TOKEN. Додай її у Render → Environment.")
    sys.exit(1)

# Канал можна теж винести у змінну середовища CHANNEL_USERNAME; за замовчуванням — твій канал
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@stock_news_ua")

# RSS-стрічки Yahoo Finance (широке покриття ринку: S&P500, Nasdaq, акції)
FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?lang=en-US&region=US",
    # Можеш додати додаткові RSS сюди
]

# Скільки новин публікувати за один запуск (раз на 2 години)
BATCH_SIZE = 3

# Куди записуємо опубліковані посилання (щоб не дублювати)
HISTORY_FILE = "posted_links.json"
HISTORY_LIMIT = 300  # зберігати останні 300 посилань

# Логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("stock_news_ua")

# Ініціалізація Telegram та перекладача
bot = telebot.TeleBot(BOT_TOKEN)
translator = Translator()

# =========================
#     ДОПОМОЖНІ ФУНКЦІЇ
# =========================
def load_history():
    """Зчитуємо список опублікованих посилань з файлу."""
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data if isinstance(data, list) else [])
    except FileNotFoundError:
        return set()
    except Exception as e:
        log.warning(f"Не вдалося прочитати історію ({HISTORY_FILE}): {e}")
        return set()

def save_history(link_set):
    """Зберігаємо історію посилань у файл (обмежуємо до HISTORY_LIMIT)."""
    try:
        arr = list(link_set)
        if len(arr) > HISTORY_LIMIT:
            arr = arr[-HISTORY_LIMIT:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(arr, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"Не вдалося зберегти історію ({HISTORY_FILE}): {e}")

POSTED = load_history()

def fetch_entries_from_feeds(max_items=10):
    """Збирає останні записи з RSS-стрічок та повертає відсортований список (найновіші першими)."""
    entries = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                log.warning(f"RSS попередження/помилка для {url}: {feed.bozo_exception}")
            if not feed.entries:
                continue
            entries.extend(feed.entries)
        except Exception as e:
            log.error(f"Помилка читання RSS {url}: {e}")

    # Сортуємо за датою публікації, якщо вона є
    def sort_key(e):
        return e.get("published_parsed") or e.get("updated_parsed") or 0

    entries.sort(key=sort_key, reverse=True)
    return entries[:max_items]

def extract_image_url(entry):
    """Намагається дістати URL зображення з RSS-запису (media_content, enclosure тощо)."""
    # 1) media_content
    media = getattr(entry, "media_content", None)
    if media and isinstance(media, list):
        for m in media:
            url = m.get("url")
            if url:
                return url

    # 2) links з type image/*
    for l in entry.get("links", []):
        if l.get("type", "").startswith("image/") and l.get("href"):
            return l["href"]

    # 3) media_thumbnail
    thumbs = getattr(entry, "media_thumbnail", None)
    if thumbs and isinstance(thumbs, list):
        for t in thumbs:
            url = t.get("url")
            if url:
                return url

    return None

def translate_title(title):
    """Переклад на українську з fallback на оригінал."""
    try:
        return translator.translate(title, dest="uk").text
    except Exception as e:
        log.warning(f"Переклад не вдався: {e}")
        return title

def post_item(title, link, image_url=None):
    """Надсилає один пост у канал: заголовок (укр) + посилання, опційно картинка."""
    title_uk = translate_title(title)
    caption = f"📰 {title_uk}\n🔗 Джерело: {link}"

    try:
        if image_url:
            bot.send_photo(CHANNEL_USERNAME, image_url, caption=caption)
        else:
            bot.send_message(CHANNEL_USERNAME, caption, disable_web_page_preview=False)
        log.info(f"Опубліковано: {title_uk}")
        return True
    except Exception as e:
        log.error(f"Помилка надсилання в Telegram: {e}")
        return False

# =========================
#     ОСНОВНА ЛОГІКА
# =========================
def post_news_batch():
    """Кожні 2 години публікує до BATCH_SIZE (3) новин без дублів."""
    global POSTED
    entries = fetch_entries_from_feeds(max_items=20)  # беремо запасом, відфільтруємо дублікати
    if not entries:
        log.info("RSS: новин не знайдено, спробуємо пізніше.")
        return

    sent = 0
    for e in entries:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue

        if link in POSTED:
            continue

        img = extract_image_url(e)
        if post_item(title, link, image_url=img):
            POSTED.add(link)
            save_history(POSTED)
            sent += 1

        if sent >= BATCH_SIZE:
            break

    if sent == 0:
        log.info("Немає нових новин для публікації (усе вже постили).")

# =========================
#     FLASK (Render keep-alive)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Stock News UA bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)

# =========================
#     ГОЛОВНИЙ ЦИКЛ
# =========================
def main_loop():
    log.info("Бот запущений. Кожні 2 години публікує 3 новини.")
    # перша спроба одразу після старту
    try:
        post_news_batch()
    except Exception as e:
        log.error(f"Помилка першої публікації: {e}")

    while True:
        time.sleep(7200)  # 2 години
        try:
            post_news_batch()
        except Exception as e:
            log.error(f"Помилка у циклі: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main_loop()
