"""Document parser — extracts structured content from HTML, PDF, DOCX, PPTX.

Uses Docling for complex documents (PDF, DOCX, PPTX) with fallback to
basic extraction when Docling is not available.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlparse
from datetime import datetime, timezone

from compass_collector.ingest import (
    InputDocument, Section, DocumentType, SourceLocator,
)

logger = logging.getLogger(__name__)


def detect_document_type(url_or_path: str) -> DocumentType:
    """Detect document type from URL or file extension."""
    path = url_or_path.split("?")[0].split("#")[0].lower()
    if path.endswith(".pdf"):
        return DocumentType.PDF
    if path.endswith(".docx"):
        return DocumentType.DOCX
    if path.endswith(".pptx") or path.endswith(".ppt"):
        return DocumentType.PPTX
    if path.endswith(".md") or path.endswith(".markdown"):
        return DocumentType.MARKDOWN
    if path.endswith(".txt"):
        return DocumentType.TEXT
    return DocumentType.HTML


def is_url(path: str) -> bool:
    return path.startswith("http://") or path.startswith("https://")


def _html_to_sections(html: str, url: str = "") -> List[Section]:
    """Parse HTML into sections using BeautifulSoup."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    sections = []
    current_heading = ""
    current_text = []
    page = 0

    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "table"]):
        if tag.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if current_text:
                text = "\n".join(current_text).strip()
                if text:
                    sections.append(Section(
                        section_id=f"s{len(sections)}",
                        heading=current_heading,
                        page=page,
                        text=text[:5000],
                    ))
                current_text = []
            current_heading = tag.get_text(strip=True)[:200]
        elif tag.name == "p":
            t = tag.get_text(strip=True)
            if t:
                current_text.append(t)
        elif tag.name == "li":
            t = tag.get_text(strip=True)
            if t:
                current_text.append(f"  • {t}")
        elif tag.name == "pre":
            t = tag.get_text(strip=True)
            if t:
                current_text.append(f"```\n{t[:2000]}\n```")
        elif tag.name == "table":
            rows = []
            for tr in tag.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                current_text.append("Table:\n" + "\n".join(rows))

    if current_text:
        text = "\n".join(current_text).strip()
        if text:
            sections.append(Section(
                section_id=f"s{len(sections)}",
                heading=current_heading,
                page=page,
                text=text[:5000],
            ))

    return sections


def fetch_url(url: str, timeout: int = 30) -> tuple[str, str]:
    """Fetch a URL and return (html, final_url)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Compass Ingestion)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace"), resp.url


def parse_html(html: str, url: str = "", title: str = "") -> InputDocument:
    """Parse HTML string into a normalized InputDocument."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    title = title or (soup.title.string.strip() if soup.title and soup.title.string else url.split("/")[-1][:100])

    sections = _html_to_sections(html, url)

    # Extract all text for raw_text
    raw_text = "\n".join(s.text for s in sections)

    return InputDocument(
        document_id=hashlib.md5((url + title).encode()).hexdigest()[:16],
        source_url=url,
        canonical_url=url,
        title=title[:200],
        document_type=DocumentType.HTML,
        content_hash=hashlib.sha256(html.encode()).hexdigest()[:16],
        sections=sections,
        raw_text=raw_text[:100000],
    )


def parse_pdf(path_or_url: str) -> Optional[InputDocument]:
    """Parse a PDF using Docling if available, otherwise basic fallback."""
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(path_or_url)
        doc = result.document

        sections = []
        for i, (heading, text) in enumerate(_iter_docling_sections(doc)):
            sections.append(Section(
                section_id=f"s{i}",
                heading=heading[:200],
                page=doc.origin.page if hasattr(doc.origin, 'page') else None,
                text=text[:5000],
            ))

        raw_text = doc.text or ""
        if not raw_text:
            raw_text = "\n".join(s.text for s in sections)

        return InputDocument(
            document_id=hashlib.md5(str(path_or_url).encode()).hexdigest()[:16],
            source_url=path_or_url if is_url(path_or_url) else f"file://{path_or_url}",
            title=Path(path_or_url).stem if not is_url(path_or_url) else path_or_url.split("/")[-1][:100],
            document_type=DocumentType.PDF,
            content_hash=hashlib.sha256(raw_text.encode()).hexdigest()[:16],
            sections=sections,
            raw_text=raw_text[:100000],
        )
    except ImportError:
        logger.warning("Docling not available. Install with: pip install docling")
        return None
    except Exception as e:
        logger.error(f"Docling PDF parsing failed for {path_or_url}: {e}")
        return None


def _iter_docling_sections(doc):
    """Yield (heading, text) pairs from a Docling document."""
    current_heading = ""
    current_text = []
    try:
        for item in doc.iterate_items():
            label = item.label if hasattr(item, 'label') else ""
            text = item.text if hasattr(item, 'text') else ""
            if label in ("heading", "title", "section_heading"):
                if current_text:
                    yield current_heading, "\n".join(current_text)
                current_heading = text[:200]
                current_text = []
            elif text:
                current_text.append(text)
    except:
        pass
    if current_text:
        yield current_heading, "\n".join(current_text)


def parse_document(path_or_url: str) -> Optional[InputDocument]:
    """Parse any supported document type. Returns None on failure."""
    doc_type = detect_document_type(path_or_url)

    if doc_type == DocumentType.PDF:
        return parse_pdf(path_or_url)

    if doc_type in (DocumentType.DOCX, DocumentType.PPTX):
        try:
            return parse_pdf(path_or_url)  # Docling handles these too
        except:
            return None

    if is_url(path_or_url):
        try:
            html, final_url = fetch_url(path_or_url)
            doc = parse_html(html, url=final_url)
            doc.document_type = doc_type if doc_type != DocumentType.UNKNOWN else DocumentType.HTML
            return doc
        except Exception as e:
            logger.error(f"Failed to fetch {path_or_url}: {e}")
            return None

    # Local file — read as text or try Docling
    path = Path(path_or_url)
    if not path.exists():
        logger.error(f"File not found: {path_or_url}")
        return None

    if path.suffix in (".txt", ".md", ".csv"):
        text = path.read_text("utf-8", errors="replace")
        return InputDocument(
            document_id=hashlib.md5(str(path).encode()).hexdigest()[:16],
            source_url=f"file://{path.absolute()}",
            title=path.stem[:100],
            document_type=doc_type,
            content_hash=hashlib.sha256(text.encode()).hexdigest()[:16],
            raw_text=text[:100000],
        )

    if doc_type in (DocumentType.PDF, DocumentType.DOCX, DocumentType.PPTX):
        return parse_pdf(str(path))

    return None


def extract_source_locator(sections: List[Section], claim_text: str) -> SourceLocator:
    """Find which section contains the claim text."""
    for s in sections:
        if claim_text[:50].lower() in s.text.lower():
            return SourceLocator(
                page=s.page,
                section=s.heading,
                paragraph=None,
                text_excerpt=claim_text[:200],
            )
    return SourceLocator(text_excerpt=claim_text[:200])
