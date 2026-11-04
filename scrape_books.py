"""books.toscrape.com から書籍のタイトル・価格・在庫状況を集めて Markdown に保存する。

- robots.txt を読み込み、禁止されたパスにはアクセスしない
- リクエストの間に 1〜3 秒のランダムな待機を入れる
- 接続エラーが起きたらログにエラーを出力して終了する

使い方:
    .venv\\Scripts\\python.exe scrape_books.py
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
from bs4 import BeautifulSoup

# certifi ではなく OS (Windows) の証明書ストアで検証する。
# ウイルス対策ソフトの HTTPS 検査など、OS が信頼するルート証明書を使う環境でも動くようにするため。
truststore.inject_into_ssl()

BASE_URL = "https://books.toscrape.com/"
USER_AGENT = "python-automation-book-scraper/1.0"
TIMEOUT_SECONDS = 10
WAIT_RANGE_SECONDS = (1.0, 3.0)

PROJECT_DIR = Path(__file__).resolve().parent
LOG_FILE = PROJECT_DIR / "logs" / "scrape_books.log"

logger = logging.getLogger("scrape_books")


@dataclass
class Book:
    title: str
    price: str
    availability: str


class PoliteSession:
    """robots.txt の確認とリクエスト間の待機をまとめて行う HTTP クライアント。"""

    def __init__(self, base_url: str) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = RobotFileParser()
        self._has_requested = False
        self._load_robots(urljoin(base_url, "/robots.txt"))

    def _load_robots(self, robots_url: str) -> None:
        logger.info("robots.txt を確認します: %s", robots_url)
        response = self._request(robots_url)
        if response.status_code in (401, 403):
            # 標準ライブラリと同じく、アクセス拒否なら全パスを禁止扱いにする
            logger.warning("robots.txt の取得が拒否されました (HTTP %s)。全パスを禁止として扱います", response.status_code)
            self.robots.disallow_all = True
        elif response.status_code >= 400:
            # 存在しない (404 など) 場合は制限なしとして扱う
            logger.info("robots.txt がありません (HTTP %s)。制限なしとして扱います", response.status_code)
            self.robots.allow_all = True
        else:
            self.robots.parse(response.text.splitlines())
            logger.info("robots.txt を読み込みました")

    def _wait(self) -> None:
        if self._has_requested:
            seconds = random.uniform(*WAIT_RANGE_SECONDS)
            logger.debug("%.1f 秒待機します", seconds)
            time.sleep(seconds)
        self._has_requested = True

    def _request(self, url: str) -> requests.Response:
        self._wait()
        return self.session.get(url, timeout=TIMEOUT_SECONDS)

    def can_fetch(self, url: str) -> bool:
        return self.robots.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> requests.Response | None:
        """robots.txt で許可されていれば取得する。禁止されていれば None を返す。"""
        if not self.can_fetch(url):
            logger.warning("robots.txt で禁止されているためスキップします: %s", url)
            return None
        response = self._request(url)
        response.raise_for_status()
        return response


def parse_books(html: bytes) -> tuple[list[Book], str | None]:
    """一覧ページから書籍情報と「次のページ」への相対リンクを取り出す。"""
    soup = BeautifulSoup(html, "html.parser")
    books: list[Book] = []
    for item in soup.select("article.product_pod"):
        link = item.select_one("h3 a")
        price = item.select_one("p.price_color")
        availability = item.select_one("p.availability")
        books.append(
            Book(
                # 一覧の表示は省略されるので、title 属性から完全なタイトルを取る
                title=(link.get("title") or link.get_text()).strip() if link else "",
                price=price.get_text(strip=True) if price else "",
                availability=availability.get_text(strip=True) if availability else "",
            )
        )
    next_link = soup.select_one("li.next a")
    return books, (next_link.get("href") if next_link else None)


def scrape_all(client: PoliteSession, start_url: str) -> list[Book]:
    books: list[Book] = []
    url: str | None = start_url
    page = 0
    while url:
        page += 1
        logger.info("ページ %d を取得します: %s", page, url)
        response = client.get(url)
        if response is None:
            break
        page_books, next_href = parse_books(response.content)
        books.extend(page_books)
        logger.info("  %d 件取得（累計 %d 件）", len(page_books), len(books))
        url = urljoin(url, next_href) if next_href else None
    return books


def escape_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def write_markdown(books: list[Book], path: Path, scraped_on: date) -> None:
    in_stock = sum(1 for b in books if "in stock" in b.availability.lower())
    lines = [
        f"# 書籍一覧（{scraped_on:%Y-%m-%d}）",
        "",
        f"- 取得元: {BASE_URL}",
        f"- 件数: {len(books)} 件（在庫あり {in_stock} 件）",
        "",
        "| No. | タイトル | 価格 | 在庫状況 |",
        "| ---: | --- | ---: | --- |",
    ]
    for i, book in enumerate(books, start=1):
        lines.append(
            f"| {i} | {escape_cell(book.title)} | {escape_cell(book.price)} | {escape_cell(book.availability)} |"
        )
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
    try:
        client = PoliteSession(BASE_URL)
        books = scrape_all(client, BASE_URL)
    except (requests.ConnectionError, requests.Timeout) as e:
        logger.error("接続エラーが発生したため終了します: %s", e)
        return 1
    except requests.RequestException as e:
        logger.error("HTTP エラーが発生したため終了します: %s", e)
        return 1

    if not books:
        logger.error("書籍を 1 件も取得できませんでした")
        return 1

    today = date.today()
    output = PROJECT_DIR / f"books_{today:%Y%m%d}.md"
    write_markdown(books, output, today)
    logger.info("%d 件を保存しました: %s", len(books), output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
