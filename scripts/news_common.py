"""Shared constants and validation helpers for the daily news brief."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
MAX_SECTION_ITEMS = 10


@dataclass(frozen=True)
class ChineseTextStats:
    """Script counts used to distinguish product names from English prose."""

    cjk_chars: int
    latin_chars: int
    latin_words: int
    prose_latin_chars: int
    prose_latin_words: int


# These are prose signals, not a whitelist of publishers or people.  Capitalised
# names are handled structurally below, while ordinary untranslated English is
# still counted even when an RSS headline uses title case.
ENGLISH_PROSE_WORDS = {
    "a", "about", "after", "against", "all", "also", "an", "and", "are", "as", "at",
    "be", "been", "before", "but", "by", "could", "did", "do", "for", "from", "has",
    "have", "he", "her", "his", "how", "in", "into", "is", "it", "its", "may", "more",
    "new", "not", "of", "on", "or", "over", "report", "says", "she", "that", "the",
    "their", "this", "to", "under", "up", "was", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would",
}


def chinese_text_stats(value: str) -> ChineseTextStats:
    """Count Chinese text and likely English prose, ignoring URLs and name-like tokens."""
    without_urls = re.sub(r"https?://\S+|www\.\S+", " ", value)
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", without_urls))
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.'’-]*", without_urls)
    prose: list[str] = []
    for token in tokens:
        bare = token.strip(".'’- ")
        folded = bare.casefold()
        acronym = len(bare) <= 12 and bare.isupper()
        mixed_case_or_product = any(c.islower() for c in bare) and any(c.isupper() for c in bare[1:])
        title_name = bare[:1].isupper() and bare[1:].islower() and folded not in ENGLISH_PROSE_WORDS
        if not (acronym or mixed_case_or_product or title_name):
            prose.append(bare)

    # Four or more adjacent Latin words are a likely untranslated phrase, even
    # if a publisher supplied a title-cased headline. Acronyms/products remain
    # exempt so "OpenAI CEO Sam Altman" can occur naturally in Chinese copy.
    token_pattern = r"[A-Za-z][A-Za-z0-9.'’-]*"
    for run in re.findall(rf"{token_pattern}(?:[\s,:;()\-–—]+{token_pattern}){{3,}}", without_urls):
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.'’-]*", run):
            if not (token.isupper() or (any(c.islower() for c in token) and any(c.isupper() for c in token[1:]))):
                prose.append(token.strip(".'’- "))
    # Runs can add an already-classified word; counts should describe unique
    # occurrences rather than inflate the failure signal.
    prose_counts: dict[str, int] = {}
    for token in prose:
        prose_counts[token] = max(prose_counts.get(token, 0), tokens.count(token))
    prose_words = [token for token, count in prose_counts.items() for _ in range(count)]
    return ChineseTextStats(
        cjk_chars=cjk_chars,
        latin_chars=sum(c.isalpha() and c.isascii() for c in without_urls),
        latin_words=len(tokens),
        prose_latin_chars=sum(sum(c.isalpha() and c.isascii() for c in token) for token in prose_words),
        prose_latin_words=len(prose_words),
    )


def chinese_dominant(value: str) -> bool:
    """Accept Chinese copy with names/acronyms, but reject untranslated English prose."""
    stats = chinese_text_stats(value)
    return stats.cjk_chars >= 2 and stats.cjk_chars >= stats.prose_latin_chars


def chinese_failure(kind: str, value: str) -> str:
    stats = chinese_text_stats(value)
    excerpt = re.sub(r"\s+", " ", value).strip()
    return (
        f'{kind} is not Chinese-dominant: "{excerpt}" '
        f"[CJK chars={stats.cjk_chars}, Latin chars={stats.latin_chars}, "
        f"Latin words={stats.latin_words}, likely-English chars={stats.prose_latin_chars}, "
        f"likely-English words={stats.prose_latin_words}]"
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
    duplicate_links = sorted({link for link in links if links.count(link) > 1})
    if duplicate_links:
        errors.append(
            "brief reuses external source URLs across event cards: "
            + ", ".join(duplicate_links)
        )
    titles = [re.sub(r"\s+", " ", x).strip().casefold() for x in re.findall(r"<h3>(.*?)</h3>", text)]
    if len(titles) != len(set(titles)):
        errors.append("brief contains duplicate event titles")
    if "ENGLISH SOURCES" not in text:
        errors.append("English-source marker is missing")
    parser = BriefTextParser()
    parser.feed(text)
    card_count = sum(parser.section_counts.values())
    declared = re.search(r'<span class="pill">(\d+) 件独立事件</span>', text)
    if declared and int(declared.group(1)) != card_count:
        errors.append(
            f"brief declares {declared.group(1)} independent events but contains {card_count} event cards"
        )
    for section_id, count in parser.section_counts.items():
        if count > MAX_SECTION_ITEMS:
            errors.append(f"section #{section_id} contains {count} events; maximum is {MAX_SECTION_ITEMS}")
    errors.extend(chinese_failure("news title", value) for value in parser.titles if not chinese_dominant(value))
    errors.extend(chinese_failure("news summary", value) for value in parser.summaries if not chinese_dominant(value))
    body = "".join(parser.titles + parser.summaries + parser.editorial)
    body_stats = chinese_text_stats(body)
    if not body or body_stats.cjk_chars < body_stats.prose_latin_chars:
        errors.append("brief editorial body is not primarily Chinese")
    return errors


class BriefTextParser(HTMLParser):
    """Extract editorial text while deliberately excluding source names/URLs."""

    def __init__(self) -> None:
        super().__init__()
        self.titles: list[str] = []
        self.summaries: list[str] = []
        self.editorial: list[str] = []
        self._target: str | None = None
        self._buffer: list[str] = []
        self._in_card = False
        self._section: str | None = None
        self.section_counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if tag == "section":
            self._section = dict(attrs).get("id")
        if tag == "article" and "card" in classes.split():
            self._in_card = True
            if self._section:
                self.section_counts[self._section] = self.section_counts.get(self._section, 0) + 1
        if tag == "h3" and self._in_card:
            self._target = "title"
            self._buffer = []
        elif tag == "p" and self._in_card:
            self._target = "summary"
            self._buffer = []
        elif tag == "p" and any(name in classes.split() for name in ("lead",)):
            self._target = "editorial"
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h3", "p"):
            if self._target and self._buffer:
                value = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
                if value:
                    getattr(self, {"title": "titles", "summary": "summaries", "editorial": "editorial"}[self._target]).append(value)
            self._target = None
            self._buffer = []
        if tag == "article":
            self._in_card = False
        elif tag == "section":
            self._section = None

    def handle_data(self, data: str) -> None:
        if self._target:
            self._buffer.append(data)
