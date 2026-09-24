import html
import logging
import os
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import httpx
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# Load environment variables from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

FEEDS = {
    "spectrum": {
        "name": "⚡ IEEE Spectrum",
        "url": "https://spectrum.ieee.org/feeds/feed.rss",
        "type": "rss",
    },
    "pes": {
        "name": "⚡ IEEE Power & Energy (PES)",
        "url": "https://ieee-pes.org/about-pes/newsroom/",
        "type": "pes_html",
    },
    "computer": {
        "name": "💻 IEEE Computer Society",
        "url": "https://www.computer.org/publications/tech-news",
        "type": "computer_html",
    },
}


async def fetch_spectrum_rss(url: str, limit: int = 5) -> list[dict]:
    """Fetch headlines from IEEE Spectrum RSS Feed."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()

    root = ET.fromstring(response.content)
    articles = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title", default="No Title").strip()
        link = item.findtext("link", default="").strip()
        if title and link:
            articles.append({"title": html.unescape(title), "link": link})
    return articles


async def fetch_pes_html(url: str, limit: int = 5) -> list[dict]:
    """Fetch headlines from IEEE PES Newsroom HTML."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles = []
    seen_links = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/news/" in href and not href.endswith("/news/") and href not in seen_links:
            title = a_tag.get_text(strip=True)
            if title and "read more" not in title.lower() and len(title) > 15:
                seen_links.add(href)
                articles.append({"title": html.unescape(title), "link": href})
                if len(articles) >= limit:
                    break

    return articles


async def fetch_computer_html(url: str, limit: int = 5) -> list[dict]:
    """Fetch headlines from IEEE Computer Society Tech News HTML."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles = []
    seen_links = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/publications/tech-news/" in href and href not in seen_links:
            title = a_tag.get_text(strip=True)
            if title and "read more" not in title.lower() and len(title) > 15:
                seen_links.add(href)
                full_link = href if href.startswith("http") else f"https://www.computer.org{href}"
                articles.append({"title": html.unescape(title), "link": full_link})
                if len(articles) >= limit:
                    break

    return articles


async def fetch_headlines(feed_key: str, limit: int = 5) -> list[dict]:
    """Route fetching based on feed type."""
    feed_info = FEEDS[feed_key]
    feed_type = feed_info["type"]

    if feed_type == "rss":
        return await fetch_spectrum_rss(feed_info["url"], limit)
    elif feed_type == "pes_html":
        return await fetch_pes_html(feed_info["url"], limit)
    elif feed_type == "computer_html":
        return await fetch_computer_html(feed_info["url"], limit)
    return []


def get_news_keyboard() -> InlineKeyboardMarkup:
    """Build inline buttons for feed selection."""
    buttons = [
        [
            InlineKeyboardButton(FEEDS["spectrum"]["name"], callback_data="spectrum"),
        ],
        [
            InlineKeyboardButton(FEEDS["pes"]["name"], callback_data="pes"),
        ],
        [
            InlineKeyboardButton(FEEDS["computer"]["name"], callback_data="computer"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /start command."""
    welcome_msg = (
        "👋 *Welcome to the IEEE Tech News Bot!*\n\n"
        "Get the latest technical news and headlines directly from IEEE publications.\n\n"
        "Select an IEEE news source below or type `/news` anytime:"
    )
    if update.message:
        await update.message.reply_text(
            welcome_msg,
            parse_mode="Markdown",
            reply_markup=get_news_keyboard(),
        )


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /news command."""
    if update.message:
        await update.message.reply_text(
            "📰 *Select an IEEE news source:*",
            parse_mode="Markdown",
            reply_markup=get_news_keyboard(),
        )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for inline button clicks."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    feed_key = query.data
    if feed_key not in FEEDS:
        await query.edit_message_text("Unknown source selected.")
        return

    feed_info = FEEDS[feed_key]
    await query.edit_message_text(f"⏳ Fetching top headlines from {feed_info['name']}...")

    try:
        articles = await fetch_headlines(feed_key, limit=5)

        if not articles:
            await query.edit_message_text(
                f"No articles found for {feed_info['name']}.",
                reply_markup=get_news_keyboard(),
            )
            return

        message_lines = [f"<b>{feed_info['name']} Top Headlines:</b>\n"]
        for idx, article in enumerate(articles, 1):
            escaped_title = (
                article["title"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            message_lines.append(f"{idx}. <a href=\"{article['link']}\">{escaped_title}</a>")

        message_lines.append("\nSelect another source below:")
        final_text = "\n".join(message_lines)

        await query.edit_message_text(
            final_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_news_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error fetching headlines for {feed_key}: {e}")
        await query.edit_message_text(
            "❌ Failed to fetch news headlines. Please try again later.",
            reply_markup=get_news_keyboard(),
        )


def main() -> None:
    """Start the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("TELEGRAM_BOT_TOKEN environment variable is missing or placeholder! Check your .env file.")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("IEEE News Bot started successfully! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
