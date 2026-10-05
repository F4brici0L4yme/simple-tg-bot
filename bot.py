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
    # --- Tier 1: plain RSS (verified 2026-10-05) ---
    "hn": {
        "name": "🟧 Hacker News",
        "url": "https://news.ycombinator.com/rss",
        "type": "rss",
        # HN returns 419 with a browser UA; use no custom headers.
        "headers": {},
    },
    "tomshardware": {
        "name": "🖥️ Tom's Hardware",
        "url": "https://www.tomshardware.com/feeds.xml",
        "type": "rss",
    },
    "theregister": {
        "name": "📡 The Register",
        "url": "https://www.theregister.com/headlines.atom",
        "type": "rss",
    },
    "mit_techreview": {
        "name": "🎓 MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "type": "rss",
    },
    "sciencenews": {
        "name": "🔬 Science News",
        "url": "https://www.sciencenews.org/feed",
        "type": "rss",
    },
    "infoq": {
        "name": "📚 InfoQ",
        "url": "https://feed.infoq.com/",
        "type": "rss",
    },
    "openai": {
        "name": "🤖 OpenAI News",
        "url": "https://openai.com/news/rss.xml",
        "type": "rss",
    },
    "githubblog": {
        "name": "🐙 GitHub Blog",
        "url": "https://github.blog/feed/",
        "type": "rss",
    },
    "nvidia": {
        "name": "💚 NVIDIA Blog",
        "url": "https://blogs.nvidia.com/feed/",
        "type": "rss",
    },
    "ars": {
        "name": "🧪 Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "type": "rss",
    },
    # --- Tier 2: HTML scraping (no public RSS) ---
    "datacamp": {
        "name": "📊 DataCamp Blog",
        "url": "https://www.datacamp.com/blog",
        "type": "datacamp_html",
    },
    "claude": {
        "name": "🟠 Claude Blog",
        "url": "https://claude.com/blog",
        "type": "claude_html",
    },
}


async def fetch_rss(url: str, limit: int = 5, headers: dict | None = None) -> list[dict]:
    """Fetch headlines from an RSS (or RSS-shaped Atom) feed.

    Handles both <item> (RSS) and <entry> (Atom) payloads, and Atom-style
    <link href="..."/> elements.
    """
    hdrs = HEADERS if headers is None else headers
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=hdrs) as client:
        response = await client.get(url)
        response.raise_for_status()

    root = ET.fromstring(response.content)
    articles = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title", default="") or "").strip()
        link = (item.findtext("link", default="") or "").strip()
        if title and link:
            articles.append({"title": html.unescape(title), "link": link})

    if len(articles) < limit:
        # Atom fallback: <entry> with <link href="..."/>
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns)[:limit]:
            title_el = entry.find("a:title", ns)
            link_el = entry.find("a:link", ns)
            title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
            link = ""
            if link_el is not None:
                link = link_el.get("href", "") or (link_el.text or "").strip()
            if title and link:
                articles.append({"title": html.unescape(title), "link": link})
            if len(articles) >= limit:
                break
    return articles


async def fetch_spectrum_rss(url: str, limit: int = 5) -> list[dict]:
    """Back-compat wrapper kept for existing callers/tests."""
    return await fetch_rss(url, limit)


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
        # Tech-news articles live under /publications/tech-news/, but
        # announcements (e.g. election results) live under /press-room/.
        if (
            "/publications/tech-news/" not in href
            and "/press-room/" not in href
        ) or href in seen_links:
            continue
        title = a_tag.get_text(strip=True)
        if title and "read more" not in title.lower() and len(title) > 15:
            seen_links.add(href)
            full_link = href if href.startswith("http") else f"https://www.computer.org{href}"
            articles.append({"title": html.unescape(title), "link": full_link})
            if len(articles) >= limit:
                break

    return articles


async def fetch_blog_list_html(
    url: str, base_url: str, path_marker: str = "/blog/", limit: int = 5
) -> list[dict]:
    """Generic scraper for blogs without RSS (DataCamp, Claude).

    Collects <a> tags whose href contains path_marker, skipping
    category/index pages, deduping links.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles = []
    seen_links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if path_marker not in href:
            continue
        # Skip index/category/pagination pages — only article links.
        lowered = href.lower()
        if "categor" in lowered or lowered.rstrip("/").endswith("/blog"):
            continue
        title = a_tag.get_text(strip=True)
        if not title or len(title) < 20:
            continue
        full_link = href if href.startswith("http") else f"{base_url}{href}"
        if full_link in seen_links:
            continue
        seen_links.add(full_link)
        articles.append({"title": html.unescape(title), "link": full_link})
        if len(articles) >= limit:
            break
    return articles


async def fetch_datacamp_html(url: str, limit: int = 5) -> list[dict]:
    """Fetch headlines from the DataCamp blog, newest first.

    Articles render in chronological order inside
    <div data-test-id="all-articles"> as media-card links
    (<a data-trackid="media-card-...">) with the title in an <h2>.
    Falls back to the generic blog scraper if the markup changes.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles = []
    seen_links = set()
    container = soup.find("div", attrs={"data-test-id": "all-articles"})
    if container is not None:
        for a_tag in container.find_all("a", href=True):
            href = a_tag["href"]
            if not href.startswith("/blog/") or "categor" in href.lower():
                continue
            h2 = a_tag.find("h2")
            title = h2.get_text(strip=True) if h2 else a_tag.get_text(strip=True)
            if not title or len(title) < 15:
                continue
            full_link = f"https://www.datacamp.com{href}"
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            articles.append({"title": html.unescape(title), "link": full_link})
            if len(articles) >= limit:
                break
    if not articles:
        return await fetch_blog_list_html(url, "https://www.datacamp.com", "/blog/", limit)
    return articles


async def fetch_claude_blog_html(url: str, limit: int = 5) -> list[dict]:
    """Fetch headlines from the Claude (Anthropic) blog."""
    return await fetch_blog_list_html(url, "https://claude.com", "/blog/", limit)


async def fetch_headlines(feed_key: str, limit: int = 5) -> list[dict]:
    """Route fetching based on feed type."""
    feed_info = FEEDS[feed_key]
    feed_type = feed_info["type"]

    if feed_type == "rss":
        return await fetch_rss(
            feed_info["url"], limit, headers=feed_info.get("headers")
        )
    elif feed_type == "pes_html":
        return await fetch_pes_html(feed_info["url"], limit)
    elif feed_type == "computer_html":
        return await fetch_computer_html(feed_info["url"], limit)
    elif feed_type == "datacamp_html":
        return await fetch_datacamp_html(feed_info["url"], limit)
    elif feed_type == "claude_html":
        return await fetch_claude_blog_html(feed_info["url"], limit)
    return []


def get_news_keyboard() -> InlineKeyboardMarkup:
    """Build inline buttons for feed selection (2 columns to fit many sources)."""
    keys = list(FEEDS.keys())
    buttons = []
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(FEEDS[k]["name"], callback_data=k) for k in keys[i : i + 2]]
        buttons.append(row)
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
