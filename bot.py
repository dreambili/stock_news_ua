import asyncio
import feedparser
from googletrans import Translator
from playwright.async_api import async_playwright
from datetime import datetime
from telegram import Bot
import pytz

# === Налаштування ===
BOT_TOKEN = "8446422482:AAFvjhuxaVVOn5-DJgHMm4xJL9afJ0IMQb8"
CHANNEL_ID = "@stock_news_ua_bot"  
NEWS_FEED = "https://finance.yahoo.com/rss/"
TIMEZONE = "Europe/Kiev"

bot = Bot(token=BOT_TOKEN)
translator = Translator()

# === Функція для публікації новин ===
async def post_news():
    feed = feedparser.parse(NEWS_FEED)
    for entry in feed.entries[:5]:
        translated_title = translator.translate(entry.title, src="en", dest="uk").text
        message = f"📈 {translated_title}\n🔗 {entry.link}"
        image_url = None
        try:
            if hasattr(entry, 'media_content'):
                image_url = entry.media_content[0]['url']
        except:
            pass
        try:
            if image_url:
                await bot.send_photo(chat_id=CHANNEL_ID, photo=image_url, caption=message)
            else:
                await bot.send_message(chat_id=CHANNEL_ID, text=message)
        except Exception as e:
            print("Помилка надсилання:", e)

# === Функція для скріншота Finviz ===
async def post_finviz_map():
    url = "https://finviz.com/map.ashx?t=sec&st=w1"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url)
        await page.screenshot(path="finviz_map.png", full_page=True)
        await browser.close()

    await bot.send_photo(chat_id=CHANNEL_ID, photo=open("finviz_map.png", "rb"), caption="🗺 Карта ринку S&P 500")

# === Основний цикл ===
async def main():
    tz = pytz.timezone(TIMEZONE)
    while True:
        now = datetime.now(tz)
        
        if now.minute == 0:
            await post_news()

        if now.hour == 16 and now.minute == 30:
            await post_finviz_map()

        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
