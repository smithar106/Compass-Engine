import uuid
import hashlib
import time
import os
from datetime import datetime
from urllib.parse import urlparse, urljoin
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from compass_collector.config.settings import (
    RAW_DIR, DEFAULT_USER_AGENT, DEFAULT_RATE_LIMIT,
    DEFAULT_CONCURRENCY, MAX_RETRIES, REQUEST_TIMEOUT, CRAWL_DELAY_BACKOFF
)
from compass_collector.models.document import Document
from compass_collector.database import get_session


class CrawlEngine:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self._rate_limits = {}

    def fetch(self, url: str, source_id: str = None,
              rate_limit: float = DEFAULT_RATE_LIMIT,
              parser_type: str = "html") -> Document:
        self._apply_rate_limit(source_id, rate_limit)

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return self._save_document(url, resp, source_id, parser_type)
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(CRAWL_DELAY_BACKOFF * (attempt + 1))
                    continue
                return self._save_failed(url, source_id, str(e))

    def fetch_sitemap(self, sitemap_url: str) -> list[str]:
        resp = self.session.get(sitemap_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
        urls = []
        for loc in soup.find_all("loc"):
            urls.append(loc.text.strip())
        return urls

    def fetch_rss(self, rss_url: str) -> list[dict]:
        import feedparser
        feed = feedparser.parse(rss_url)
        entries = []
        for entry in feed.entries:
            entries.append({
                "url": entry.get("link", ""),
                "title": entry.get("title", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", "")
            })
        return entries

    def crawl_paginated(self, base_url: str, param: str = "page",
                        max_pages: int = 10, source_id: str = None) -> list[Document]:
        docs = []
        for page in range(1, max_pages + 1):
            url = f"{base_url}?{param}={page}" if "?" not in base_url else f"{base_url}&{param}={page}"
            doc = self.fetch(url, source_id)
            if doc.crawl_status == "failed":
                break
            docs.append(doc)
        return docs

    def _apply_rate_limit(self, source_id: str, rate_limit: float):
        if source_id:
            last = self._rate_limits.get(source_id, 0)
            elapsed = time.time() - last
            if elapsed < rate_limit:
                time.sleep(rate_limit - elapsed)
            self._rate_limits[source_id] = time.time()

    def _content_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _save_document(self, url: str, resp: requests.Response,
                       source_id: str, parser_type: str) -> Document:
        content_hash = self._content_hash(resp.content)

        session = get_session()
        try:
            existing = session.query(Document).filter_by(
                content_hash=content_hash, url=url
            ).first()
            if existing:
                return existing

            ext = "html" if parser_type == "html" else "pdf"
            save_dir = RAW_DIR / ext
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{content_hash[:16]}.{ext}"
            filepath = save_dir / filename

            with open(filepath, "wb") as f:
                f.write(resp.content)

            doc = Document(
                id=str(uuid.uuid4()),
                source_registry_id=source_id or "",
                url=url,
                canonical_url=resp.url,
                content_hash=content_hash,
                raw_file_path=str(filepath),
                document_type=parser_type,
                crawl_status="success",
                retrieved_at=datetime.utcnow()
            )

            if parser_type == "html":
                soup = BeautifulSoup(resp.content, "html.parser")
                doc.title = soup.title.string.strip() if soup.title else ""
                doc.language = soup.html.get("lang", "") if soup.html else ""

                clean_path = RAW_DIR / "clean" / f"{content_hash[:16]}.txt"
                clean_path.parent.mkdir(parents=True, exist_ok=True)
                clean_text = soup.get_text(separator="\n", strip=True)
                with open(clean_path, "w") as f:
                    f.write(clean_text)
                doc.clean_text_path = str(clean_path)

            session.add(doc)
            session.commit()
            return doc
        finally:
            session.close()

    def _save_failed(self, url: str, source_id: str, error: str) -> Document:
        session = get_session()
        try:
            doc = Document(
                id=str(uuid.uuid4()),
                source_registry_id=source_id or "",
                url=url,
                crawl_status="failed",
                doc_metadata={"error": error}
            )
            session.add(doc)
            session.commit()
            return doc
        finally:
            session.close()

    def close(self):
        self.session.close()
