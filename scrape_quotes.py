"""quotes.toscrape.com/js から名言のテキストと著者名を集めて Markdown に保存する。

JavaScript で描画されるページなので、Playwright で実際のブラウザを動かして取得する。

- ブラウザを画面に表示して実行する（headless=False）
- robots.txt を読み込み、禁止されたパスにはアクセスしない
- リクエストの間に 1〜3 秒のランダムな待機を入れる
- 接続エラーが起きたらログにエラーを出力して終了する
- 結果を quotes_YYYYMMDD.md、1 ページ目のスクリーンショットを quotes_YYYYMMDD.png に保存する

使い方:
    .venv\\Scripts\\python.exe scrape_quotes.py
"""

from __future__ import annotations

import logging
import random
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
import truststore
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

# robots.txt の取得 (requests) を OS の証明書ストアで検証する。
# ウイルス対策ソフトの HTTPS 検査など、OS が信頼するルート証明書を使う環境でも動くようにするため。
truststore.inject_into_ssl()

START_URL = "https://quotes.toscrape.com/js/"
USER_AGENT = "python-automation-quote-scraper/1.0"
TIMEOUT_MS = 15_000
WAIT_RANGE_SECONDS = (1.0, 3.0)

PROJECT_DIR = Path(__file__).resolve().parent
LOG_FILE = PROJECT_DIR / "logs" / "scrape_quotes.log"

logger = logging.getLogger("scrape_quotes")


class ConnectionFailed(Exception):
    """対象サイトに接続できなかったことを表す。"""


@dataclass
class Quote:
    text: str
    author: str


class Throttle:
    """リクエストの間に 1〜3 秒のランダムな待機を入れる。"""

    def __init__(self) -> None:
        self._has_requested = False

    def wait(self) -> None:
        if self._has_requested:
            seconds = random.uniform(*WAIT_RANGE_SECONDS)
            logger.info("%.1f 秒待機します", seconds)
            time.sleep(seconds)
        self._has_requested = True


def load_robots(url: str, throttle: Throttle) -> RobotFileParser:
    """robots.txt を取得して解析する。"""
    robots_url = urljoin(url, "/robots.txt")
    robots = RobotFileParser()
    logger.info("robots.txt を確認します: %s", robots_url)
    throttle.wait()
    try:
        response = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_MS / 1000)
    except requests.RequestException as e:
        raise ConnectionFailed(f"robots.txt を取得できませんでした: {e}") from e

    if response.status_code in (401, 403):
        # 標準ライブラリと同じく、アクセス拒否なら全パスを禁止扱いにする
        logger.warning("robots.txt の取得が拒否されました (HTTP %s)。全パスを禁止として扱います", response.status_code)
        robots.disallow_all = True
    elif response.status_code >= 400:
        # 存在しない (404 など) 場合は制限なしとして扱う
        logger.info("robots.txt がありません (HTTP %s)。制限なしとして扱います", response.status_code)
        robots.allow_all = True
    else:
        robots.parse(response.text.splitlines())
        logger.info("robots.txt を読み込みました")
    return robots


def launch_browser(p: Playwright) -> Browser:
    """ブラウザを画面表示モードで起動する。

    PC にインストール済みの Google Chrome を優先して使い、無ければ Playwright 付属の Chromium を使う。
    (Claude デスクトップアプリなどパッケージ化されたアプリから入れた Chromium は、
    保存先が仮想化されてサンドボックスに起動を拒否されることがあるため)
    """
    try:
        browser = p.chromium.launch(channel="chrome", headless=False)
        logger.info("Google Chrome を起動しました")
    except PlaywrightError:
        logger.info("Google Chrome が使えないため、Playwright 付属の Chromium を起動します")
        browser = p.chromium.launch(headless=False)
    return browser


def open_page(page: Page, url: str) -> None:
    """ページを開き、JavaScript で名言が描画されるまで待つ。"""
    try:
        response = page.goto(url, timeout=TIMEOUT_MS)
    except PlaywrightError as e:
        # net::ERR_NAME_NOT_RESOLVED やタイムアウトなど
        raise ConnectionFailed(f"{url} に接続できませんでした: {e.message.splitlines()[0]}") from e
    if response is not None and not response.ok:
        raise ConnectionFailed(f"{url} が HTTP {response.status} を返しました")
    page.wait_for_selector("div.quote", timeout=TIMEOUT_MS)


def extract_quotes(page: Page) -> list[Quote]:
    """表示中のページから名言と著者名を取り出す。"""
    quotes: list[Quote] = []
    for item in page.locator("div.quote").all():
        text = item.locator("span.text").inner_text().strip()
        author = item.locator("small.author").inner_text().strip()
        quotes.append(Quote(text=text, author=author))
    return quotes


def next_page_url(page: Page) -> str | None:
    """「Next」リンクがあれば絶対 URL を返す。"""
    link = page.locator("li.next a")
    if link.count() == 0:
        return None
    href = link.first.get_attribute("href")
    return urljoin(page.url, href) if href else None


def scrape_all(page: Page, robots: RobotFileParser, throttle: Throttle, screenshot_path: Path) -> list[Quote]:
    quotes: list[Quote] = []
    url: str | None = START_URL
    page_no = 0
    while url:
        if not robots.can_fetch(USER_AGENT, url):
            logger.warning("robots.txt で禁止されているためスキップします: %s", url)
            break
        page_no += 1
        logger.info("ページ %d を取得します: %s", page_no, url)
        throttle.wait()
        open_page(page, url)
        if page_no == 1:
            page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info("スクリーンショットを保存しました: %s", screenshot_path)
        page_quotes = extract_quotes(page)
        quotes.extend(page_quotes)
        logger.info("  %d 件取得（累計 %d 件）", len(page_quotes), len(quotes))
        url = next_page_url(page)
    return quotes


def escape_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def write_markdown(quotes: list[Quote], path: Path, scraped_on: date, screenshot_name: str) -> None:
    authors = {q.author for q in quotes}
    lines = [
        f"# 名言一覧（{scraped_on:%Y-%m-%d}）",
        "",
        f"- 取得元: {START_URL}",
        f"- 件数: {len(quotes)} 件（著者 {len(authors)} 人）",
        f"- スクリーンショット（1 ページ目）: [{screenshot_name}]({screenshot_name})",
        "",
        "| No. | 名言 | 著者 |",
        "| ---: | --- | --- |",
    ]
    for i, quote in enumerate(quotes, start=1):
        lines.append(f"| {i} | {escape_cell(quote.text)} | {escape_cell(quote.author)} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup_logging() -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def main() -> int:
    setup_logging()
    today = date.today()
    markdown_path = PROJECT_DIR / f"quotes_{today:%Y%m%d}.md"
    screenshot_path = PROJECT_DIR / f"quotes_{today:%Y%m%d}.png"
    throttle = Throttle()

    try:
        robots = load_robots(START_URL, throttle)
        with sync_playwright() as p:
            browser = launch_browser(p)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                quotes = scrape_all(page, robots, throttle, screenshot_path)
            finally:
                browser.close()
    except ConnectionFailed as e:
        logger.error("接続エラーが発生したため終了します: %s", e)
        return 1
    except PlaywrightError as e:
        logger.error("ブラウザ操作でエラーが発生したため終了します: %s", e.message.splitlines()[0])
        return 1

    if not quotes:
        logger.error("名言を 1 件も取得できませんでした")
        return 1

    write_markdown(quotes, markdown_path, today, screenshot_path.name)
    logger.info("%d 件を保存しました: %s", len(quotes), markdown_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
