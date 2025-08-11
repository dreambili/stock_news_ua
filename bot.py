import time
import requests
from bs4 import BeautifulSoup
from googletrans import Translator
import telebot

# === Налаштування ===
BOT_TOKEN = "8446422482:AAFvjhuxaVVOn5-DJgHMm4xJL9afJ0IMQb8"
CHANNEL_USERNAME = "@stock_news_ua"

# URL Yahoo Finance для новин про S&P 500, Nasdaq
NEWS_URLS = [
    "https://finance.yahoo.com/topic/stock-market-news/",
    "https://finance.yahoo.com/topic/investing/",
    "https://finance.yahoo.com/topic/economic-news/"
]

bot = telebot.TeleBot(BOT_TOKEN)
translator = Translator()

last_posted_link = None

def get_latest_news():
    """Отримує останню новину з Yahoo Finance"""
    global last_posted_link

    for url in NEWS_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
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
            print(f"Помилка при отриманні новин: {e}")

    return None, None

def translate_to_ukrainian(text):
    """Перекладає текст українською"""
    try:
        return translator.translate(text, dest="uk").text
    except:
        return text

def post_news():
    """Публікує останню новину в Telegram"""
    title, link = get_latest_news()
    if title and link:
        title_uk = translate_to_ukrainian(title)
        message = f"📰 {title_uk}\nДжерело: {link}"
        bot.send_message(CHANNEL_USERNAME, message, disable_web_page_preview=False)
        print(f"Опубліковано: {title_uk}")
    else:
        print("Немає нових новин.")

if __name__ == "__main__":
    print("Бот запущений...")
    while True:
        post_news()
        time.sleep(3600)  # чекати 1 годину
