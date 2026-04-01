"""Simple single-page web crawler for text extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.request import Request, urlopen


_USER_AGENT = (
    "Mozilla/5.0 (compatible; LlmDemoResearchBot/0.8; +https://example.local)"
)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "web_source"
    return cleaned[:120]


class _MainTextParser(HTMLParser):
    """Extract title and readable text from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.skip_depth = 0
        self.tags: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append(tag.lower())
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag.lower() in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self.in_title = False
        if t in {"script", "style", "noscript"} and self.skip_depth > 0:
            self.skip_depth -= 1
        if t in {"article", "main", "section", "div", "p", "li"}:
            self.text_parts.append("\n")
        if self.tags:
            self.tags.pop()

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        txt = _normalize_space(unescape(data))
        if not txt:
            return
        if self.in_title:
            self.title_parts.append(txt)
            return
        self.text_parts.append(txt)


@dataclass
class CrawledPage:
    title: str
    markdown: str


def fetch_and_extract_markdown(url: str, timeout: float = 15.0) -> CrawledPage:
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:  # nosec B310
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")
        charset = resp.headers.get_content_charset() or "utf-8"
        html = resp.read().decode(charset, errors="replace")

    parser = _MainTextParser()
    parser.feed(html)
    title = _normalize_space(" ".join(parser.title_parts)) or "web_source"
    raw_text = "\n".join(parser.text_parts)
    lines = []
    for line in raw_text.splitlines():
        s = _normalize_space(line)
        if s:
            lines.append(s)
    text = "\n\n".join(lines)
    if len(text) < 80:
        raise ValueError("Extracted page content is too short")

    fetched_at = datetime.now(timezone.utc).isoformat()
    markdown = (
        f"# {title}\n\n"
        f"- Source: {url}\n"
        f"- FetchedAt: {fetched_at}\n\n"
        f"{text}\n"
    )
    return CrawledPage(title=title, markdown=markdown)


def suggest_markdown_filename(title: str) -> str:
    return f"{_sanitize_filename(title)}.md"
