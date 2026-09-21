"""Shared constants and validation helpers for the daily news brief."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

SECTIONS = (
    ("must", "今日最重要"),
    ("ukraine", "俄乌战争"),
    ("middleeast", "中东局势"),
    ("migration", "欧美移民、庇护与边境"),
    ("ai", "AI：模型、算力、安全与监管"),
    ("robots", "人形机器人与自主系统"),
    ("energy", "能源科技、电池与先进核能"),
    ("other", "其他重大国际与科技新闻"),
)


def validate_html(path: Path, expected_date: str) -> list[str]:
    """Return human-readable validation errors for a generated briefing."""
    errors: list[str] = []
    if not path.exists():
        return [f"missing output: {path}"]
    text = path.read_text(encoding="utf-8")
    if f"私人 AI 新闻简报｜{expected_date}" not in text:
        errors.append("title does not contain the expected Singapore date")
    for section_id, _ in SECTIONS:
        if f'id="{section_id}"' not in text:
            errors.append(f"missing section #{section_id}")
    links = re.findall(r'href="(https?://[^\"]+)"', text)
    if not links:
        errors.append("brief contains no external news links")
    if any(not link.startswith(("http://", "https://")) for link in links):
        errors.append("brief contains an invalid external link")
    titles = [re.sub(r"\s+", " ", x).strip().casefold() for x in re.findall(r"<h3>(.*?)</h3>", text)]
    if len(titles) != len(set(titles)):
        errors.append("brief contains duplicate event titles")
    if "ENGLISH SOURCES" not in text:
        errors.append("English-source marker is missing")
    parser = BriefTextParser()
    parser.feed(text)
    if parser.titles and any(not chinese_dominant(value) for value in parser.titles):
        errors.append("one or more news titles are not Chinese-dominant")
    if parser.summaries and any(not chinese_dominant(value) for value in parser.summaries):
        errors.append("one or more news summaries are not Chinese-dominant")
    body = "".join(parser.titles + parser.summaries + parser.editorial)
    cjk = len(re.findall(r"[\u3400-\u9fff]", body))
    latin = len(re.findall(r"[A-Za-z]", body))
    if not body or cjk < latin:
        errors.append("brief editorial body is not primarily Chinese")
    return errors


def chinese_dominant(value: str) -> bool:
    """Allow product names such as OpenAI, but reject English prose."""
    cjk = len(re.findall(r"[\u3400-\u9fff]", value))
    latin_words = len(re.findall(r"[A-Za-z]+", value))
    return cjk >= 2 and cjk >= latin_words


class BriefTextParser(HTMLParser):
    """Extract editorial text while deliberately excluding source names/URLs."""

    def __init__(self) -> None:
        super().__init__()
        self.titles: list[str] = []
        self.summaries: list[str] = []
        self.editorial: list[str] = []
        self._target: str | None = None
        self._in_card = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if tag == "article" and "card" in classes.split():
            self._in_card = True
        if tag == "h3" and self._in_card:
            self._target = "title"
        elif tag == "p" and self._in_card:
            self._target = "summary"
        elif tag == "p" and any(name in classes.split() for name in ("lead",)):
            self._target = "editorial"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h3", "p"):
            self._target = None
        if tag == "article":
            self._in_card = False

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value or not self._target:
            return
        getattr(self, {"title": "titles", "summary": "summaries", "editorial": "editorial"}[self._target]).append(value)
