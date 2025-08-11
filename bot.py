import os
import sys
import time
import threading
import requests
from bs4 import BeautifulSoup
import telebot
from flask import Flask
from googletrans import Translator

# =====================
#   НАЛАШТУВАННЯ
# =====================
# ⚠️ Беремо токен із змінної середовища (НЕ з коду)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("[FATAL] Не задано змінну середовища BOT_TOKEN. Додай її в Render → Environment.")
    sys.exit(1)

# Канал можна задати тут, або через змінну середовища CHANNEL_USERNAME
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@stock_news_ua")

# Сторінки Yahoo Finance з новинами
NEWS_URLS = [
    "https://finance.yahoo.com/topic/stock-market-news/",
    "https://finance.yahoo.com/topic/investing/",
    "https://finance.yahoo.com/topic/economic-news/"
]

bot = telebot.TeleBot(BOT_TOKEN)
translator = Translator()
last_posted_link_path = "last_posted.txt"


def _read_last_link():
    try:
        with open(last_posted_link_path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _save_last_link(link: str):
    try:
        with open(last_posted_link_path, "w", encoding="utf-8") as f:
            f.write(link or "")
    except Exception as e:
        print(f"[WARN] Не вдалося зберегти останнє посилання: {e}")


last_posted_link = _read_last_link()


def get_latest_news():
    """Отримує (title, link) останньої новини з будь-якого з розділів."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    for url in NEWS_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # 1) спроба: стандартний елемент стрічки
            link_tag = None
            li = soup.find("li", {"class": "js-stream-content"})
            if li:
                link_tag = li.find("a", href=True)

            # 2) запасний варіант: перший лінк, що веде на /news/
            if not link_tag:
                for a in soup.select("a[href]"):
                    href = a.get("href", "")
                    if href.startswith("/news/") or "/news/" in href:
                        link_tag = a
                        break

            if not link_tag:
                continue

            href = link_tag.get("href", "")
            link = href if href.startswith("http") else "https://finance.yahoo.com" + href

            title = (link_tag.get_text() or "").strip()
            if not title and li:
                h = li.find(["h3", "h2"])
                if h:
                    title = h.get_text(strip=True)

            if title and link:
                return title, link

        except Exception as e:
            print(f"[ERROR] Отримання новин з {url}: {e}")

    return None, None


def post_one_news_if_new():
    """Перекладає та публікує новину, якщо вона нова (1 шт)."""
    global last_posted_link
    title, link = get_latest_news()
    if not title or not link:
        print("[INFO] Новини не знайдено — спробуємо пізніше.")
        return

    if link == last_posted_link:
        print("[INFO] Остання новина вже публікувалась.")
        return

    # Переклад заголовка на українську
    title_uk = title
    try:
        title_uk = translator.translate(title, dest="uk").text
    except Exception as e:
        print(f"[WARN] Переклад не вдався, публікуємо оригінал: {e}")

    msg = f"📰 {title_uk}\n🔗 Джерело: {link}"

    try:
        bot.send_message(CHANNEL_USERNAME, msg, disable_web_page_preview=False)
        print(f"[INFO] Опубліковано: {title_uk}")
        last_posted_link = link
        _save_last_link(link)
    except Exception as e:
        print(f"[ERROR] Відправка в Telegram: {e}")


# Flask-заглушка для Render (щоб сервіс бачив відкритий порт)
app = Flask(__name__)

@app.route('/')
def home():
    return "Stock News UA bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)


def main_loop():
    print("[INFO] Бот запущений. Кожну годину перевіряємо новини...")
    post_one_news_if_new()  # одразу при старті
    while True:
        time.sleep(3600)  # 1 година
        post_one_news_if_new()


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main_loop()
