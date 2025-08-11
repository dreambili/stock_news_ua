import time
import requests
from bs4 import BeautifulSoup
import telebot
import sys

# === Налаштування ===
BOT_TOKEN = "8446422482:AAFvjhuxaVVOn5-DJgHMm4xJL9afJ0IMQb8"
CHANNEL_USERNAME = "@stock_news_ua"

NEWS_URLS = [
    "https://finance.yahoo.com/topic/stock-market-news/",
    "https://finance.yahoo.com/topic/investing/",
    "https://finance.yahoo.com/topic/economic-news/"
]

bot = telebot.TeleBot(BOT_TOKEN)
last_posted_link = None

def get_latest_news():
    global last_posted_link

    for url in NEWS_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")

            article = soup.find("li", {"class": "js-stream-content"})
            if not article:
                continue

            link_tag = article.find("a")
            if not link_tag or not link_tag.get("href"):
                continue

            link = "https://finance.yahoo.com" + link_tag["href"]
            title = link_tag.get_text(strip=True)

            if link != last_posted_link:
                last_posted_link = link
                return title, link

        except Exception as e:
            print(f"[ERROR] Помилка при отриманні новин: {e}", file=sys.stderr)

    return None, None

def post_news():
    title, link = get_latest_news()
    if title and link:
        message = f"📰 {title}\nДжерело: {link}"
        try:
            bot.send_message(CHANNEL_USERNAME, message, disable_web_page_preview=False)
            print(f"[INFO] Опубліковано: {title}")
        except Exception as e:
            print(f"[ERROR] Помилка надсилання в Telegram: {e}", file=sys.stderr)
    else:
        print("[INFO] Нових новин немає.")

if __name__ == "__main__":
    print("[INFO] Бот запущений...")
    while True:
        post_news()
        time.sleep(3600)  # чекати 1 годину
