#!/usr/bin/env python3
"""Collect recent English-language news feeds and render the daily brief."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from news_common import MAX_SECTION_ITEMS, SECTIONS, chinese_failure, chinese_dominant, validate_html

SGT = ZoneInfo("Asia/Singapore")
UA = "Chatgpt-News daily briefing/1.0 (+https://github.com/sunzhe0073/Chatgpt-News)"
QUERIES = {
    "ukraine": "Ukraine Russia war OR Kyiv OR Moscow",
    "middleeast": "Middle East Gaza Israel Iran Lebanon Syria Yemen",
    "migration": "US Europe immigration asylum refugees border policy",
    "ai": "artificial intelligence AI model regulation data center chips",
    "robots": "humanoid robot robotics autonomous system",
    "energy": "energy technology battery nuclear fusion renewable grid",
    "other": "major international world news",
}
DIRECT_FEEDS = {
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "The Guardian World": "https://www.theguardian.com/world/rss",
    "The Guardian Technology": "https://www.theguardian.com/technology/rss",
    "NPR World": "https://feeds.npr.org/1004/rss.xml",
    "UN News": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
}
TOPIC_TERMS = {
    "ukraine": ("ukrain", "russia", "kyiv", "kremlin", "zelensk", "putin"),
    "middleeast": ("gaza", "israel", "iran", "hamas", "hezbollah", "leban", "syria", "yemen", "houthi", "middle east"),
    "migration": ("migrant", "immigration", "asylum", "refugee", "border", "deport", "visa"),
    "ai": ("artificial intelligence", " ai ", "openai", "anthropic", "deepmind", "nvidia", "chatgpt", "model", "data center"),
    "robots": ("robot", "humanoid", "autonomous", "automation"),
    "energy": ("energy", "battery", "nuclear", "fusion", "solar", "wind power", "grid", "hydrogen", "geothermal"),
}
LOW_QUALITY = ("opinion", "horoscope", "quiz", "podcast", "live updates", "sponsored")
MAJOR_TERMS = (
    "breaking", "war", "attack", "strike", "invasion", "ceasefire", "sanction",
    "election", "president", "prime minister", "government", "court", "dead", "killed",
    "crisis", "emergency", "billion", "trillion", "launch", "ban", "agreement", "deal",
)


@dataclass
class Item:
    title: str
    url: str
    source: str
    published: datetime
    summary: str = ""
    category: str = "other"
    sources: list[tuple[str, str]] = field(default_factory=list)


def clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def looks_english(value: str) -> bool:
    """Reject non-English feed results without penalising names or punctuation."""
    letters = re.findall(r"[A-Za-z]", value)
    cjk = re.findall(r"[\u3400-\u9fff]", value)
    return len(letters) >= 12 and not cjk


def parse_date(value: str, fallback: datetime) -> datetime:
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return fallback


def fetch(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(5_000_000)


def feed_items(payload: bytes, source_hint: str, now: datetime) -> list[Item]:
    root = ET.fromstring(payload)
    result: list[Item] = []
    nodes = root.findall(".//item")
    if not nodes:  # Atom
        nodes = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for node in nodes:
        def value(*names: str) -> str:
            for name in names:
                child = node.find(name)
                if child is not None and child.text:
                    return child.text
            return ""
        title = clean(value("title", "{http://www.w3.org/2005/Atom}title"))
        link = value("link")
        if not link:
            atom_link = node.find("{http://www.w3.org/2005/Atom}link")
            link = atom_link.get("href", "") if atom_link is not None else ""
        description = clean(value("description", "{http://www.w3.org/2005/Atom}summary", "{http://purl.org/rss/1.0/modules/content/}encoded"))
        published = parse_date(value("pubDate", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"), now)
        source = source_hint
        source_node = node.find("source")
        if source_node is not None and source_node.text:
            source = clean(source_node.text)
        if title and link.startswith(("http://", "https://")):
            result.append(Item(title, link, source, published, description))
    return result


def canonical_words(title: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "as", "at", "is", "are", "says", "after", "from"}
    return {w for w in re.findall(r"[a-z0-9]+", title.casefold()) if len(w) > 2 and w not in stop}


def category_for(item: Item, hinted: str) -> str:
    text = f" {item.title} {item.summary} ".casefold()
    scores = {key: sum(term in text for term in terms) for key, terms in TOPIC_TERMS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else hinted


def source_score(source: str, url: str) -> int:
    text = f"{source} {url}".casefold()
    score = 3 if any(x in text for x in ("reuters", "bbc", "ap news", "apnews", "associated press", "guardian", "npr", "un news", "news.un.org", ".gov", ".int")) else 0
    return score


def publisher_key(item: Item) -> str:
    """Return a stable publisher identity for diversity scoring."""
    source = re.sub(r"\s+(world|technology|news)$", "", item.source.casefold()).strip()
    host = urllib.parse.urlsplit(item.url).hostname or ""
    return source or host.removeprefix("www.")


def title_similarity(left: Item, right: Item) -> float:
    a, b = canonical_words(left.title), canonical_words(right.title)
    return len(a & b) / max(1, min(len(a), len(b)))


def ranking_score(item: Item, category: str, newest: datetime) -> float:
    """Score freshness, authority, topic fit and major-event signals deterministically."""
    age_hours = max(0.0, (newest - item.published).total_seconds() / 3600)
    freshness = max(0.0, 36.0 - age_hours) / 6.0
    text = f" {item.title} {item.summary} ".casefold()
    relevance = sum(term in text for term in TOPIC_TERMS.get(category, ()))
    major = sum(bool(re.search(rf"\b{re.escape(term)}\b", text)) for term in MAJOR_TERMS)
    completeness = min(len(clean(item.summary)), 400) / 200
    corroboration = min(len(item.sources), 3) - 1
    return freshness + source_score(item.source, item.url) * 2.0 + relevance * 1.5 + major * 1.25 + completeness + corroboration


def select_section(items: list[Item], category: str, limit: int = MAX_SECTION_ITEMS) -> list[Item]:
    """Select a diverse, high-quality section using a deterministic MMR-like rank."""
    if not items or limit <= 0:
        return []
    newest = max(item.published for item in items)
    remaining = list(items)
    selected: list[Item] = []
    publisher_counts: dict[str, int] = {}
    while remaining and len(selected) < limit:
        def score(item: Item) -> tuple[float, datetime, str, str]:
            duplicate_penalty = max((title_similarity(item, chosen) for chosen in selected), default=0.0) * 8
            publisher_penalty = publisher_counts.get(publisher_key(item), 0) * 2.5
            value = ranking_score(item, category, newest) - duplicate_penalty - publisher_penalty
            return (value, item.published, item.title.casefold(), item.url)

        winner = max(remaining, key=score)
        selected.append(winner)
        publisher_counts[publisher_key(winner)] = publisher_counts.get(publisher_key(winner), 0) + 1
        # A looser second event check catches alternate headlines missed by the
        # primary merge, preventing one story from consuming several slots.
        remaining = [item for item in remaining if item is not winner and title_similarity(item, winner) < 0.58]
    return selected


def select_for_translation(items: list[Item]) -> list[Item]:
    """Select at most ten events per topic before invoking Argos."""
    selected: list[Item] = []
    for category, _ in SECTIONS:
        if category == "must":
            continue
        selected.extend(select_section([item for item in items if item.category == category], category))
    return selected


def deduplicate(items: list[Item]) -> list[Item]:
    groups: list[Item] = []
    for item in sorted(items, key=lambda x: x.published, reverse=True):
        words = canonical_words(item.title)
        match = None
        for existing in groups:
            other = canonical_words(existing.title)
            similarity = len(words & other) / max(1, min(len(words), len(other)))
            item_url = urllib.parse.urlsplit(item.url)._replace(query="", fragment="").geturl().rstrip("/")
            existing_url = urllib.parse.urlsplit(existing.url)._replace(query="", fragment="").geturl().rstrip("/")
            if item_url == existing_url or similarity >= 0.72:
                match = existing
                break
        if match:
            match.sources.append((item.source, item.url))
            if source_score(item.source, item.url) > source_score(match.source, match.url):
                match.title, match.url, match.source, match.summary = item.title, item.url, item.source, item.summary
        else:
            item.sources = [(item.source, item.url)]
            groups.append(item)
    for item in groups:
        unique = {(name, url) for name, url in item.sources}
        item.sources = sorted(unique, key=lambda x: source_score(*x), reverse=True)[:3]
    return groups


def load_local_translator():
    """Load the locally installed Argos English-to-Chinese model."""
    try:
        import argostranslate.translate
        from opencc import OpenCC
    except ImportError as exc:
        raise RuntimeError(
            "Local translation dependencies are missing; run scripts/setup_translation.py"
        ) from exc

    installed = argostranslate.translate.get_installed_languages()
    english = next((language for language in installed if language.code == "en"), None)
    chinese = next((language for language in installed if language.code == "zh"), None)
    if not english or not chinese:
        raise RuntimeError(
            "Argos English-to-Chinese model is missing; run scripts/setup_translation.py"
        )
    translation = english.get_translation(chinese)
    simplified = OpenCC("t2s")
    return lambda value: simplified.convert(translation.translate(value))


def summary_source(item: Item) -> str:
    """Use only publisher-supplied facts as input to the local translator."""
    description = clean(item.summary)[:900]
    if description:
        return description
    # Some RSS entries contain no description. Reusing the headline is less
    # informative, but remains factual and never invents missing context.
    return f"The report says: {item.title}. No additional summary was provided by the feed."


def postprocess_chinese(value: str, *, title: bool = False) -> str:
    """Conservatively clean Argos output without adding or rewriting facts."""
    value = clean(value)
    # Feed wrappers and Google News headlines often append the publisher even
    # though it is rendered separately from Item.source below.
    value = re.sub(
        r"\s*(?:[-–—|｜]\s*)?(?:来源[：:]\s*)?(Reuters|BBC(?: News)?|AP(?: News)?|The Guardian|Guardian|NPR|UN News)\s*$",
        "", value, flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"^(Reuters|BBC(?: News)?|AP(?: News)?|The Guardian|Guardian|NPR|UN News)\s*(?:报道|消息)?\s*[：:,，\-–—]+\s*",
        "", value, flags=re.IGNORECASE,
    )
    value = re.sub(r"^[\s\"'“”‘’]+|[\s\"'“”‘’\-–—|｜]+$", "", value)
    value = re.sub(r"([。！？!?])[\"”’]\s*[\"“‘]", r"\1", value)
    value = re.sub(r"([，。！？；：、])\1+", r"\1", value)
    value = re.sub(r"\s+([，。！？；：、])", r"\1", value)
    value = re.sub(r"([（【])\s+|\s+([）】])", lambda m: m.group(1) or m.group(2), value)
    # Convert punctuation only at Chinese boundaries, leaving URLs, numbers,
    # acronyms and product names untouched.
    value = re.sub(r"(?<=[\u3400-\u9fff])\s*,\s*(?=[\u3400-\u9fffA-Za-z])", "，", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s*;\s*(?=[\u3400-\u9fffA-Za-z])", "；", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s*:\s*(?=[\u3400-\u9fff])", "：", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\.(?=\s|$)", "。", value)
    # Remove only exact repeated sentences/fragments; do not paraphrase them.
    parts = re.split(r"(?<=[。！？!?])\s*", value)
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        key = re.sub(r"[\s。！？!?\"'“”‘’]+", "", part).casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(part.strip(" \"'“”‘’"))
    value = "".join(unique).strip()
    if title:
        value = re.sub(r"[。；;]+$", "", value).strip()
    return value


def translate_batch(items: list[Item], fixture: Path | None = None, translator=None) -> list[str]:
    """Translate publisher text locally, dropping individual unsafe results."""
    fixture_data = json.loads(fixture.read_text(encoding="utf-8")) if fixture else None
    local_translate = translator or (None if fixture_data is not None else load_local_translator())
    accepted: list[Item] = []
    warnings: list[str] = []
    for item in items:
        original_title = item.title
        if fixture_data is not None:
            value = fixture_data.get(item.title)
            if not value:
                warnings.append(f'Translation skipped "{original_title}": fixture has no entry')
                continue
            title, summary = value.get("title"), value.get("summary")
        else:
            try:
                title = local_translate(item.title)
                summary = local_translate(summary_source(item))
            except Exception as exc:
                warnings.append(f'Translation skipped "{original_title}": {type(exc).__name__}: {exc}')
                continue
        if not title or not summary:
            warnings.append(f'Translation skipped "{original_title}": omitted title or summary')
            continue
        translated_title = postprocess_chinese(str(title), title=True)
        translated_summary = postprocess_chinese(str(summary))
        failures = []
        if not chinese_dominant(translated_title):
            failures.append(chinese_failure("translated title", translated_title))
        if not chinese_dominant(translated_summary):
            failures.append(chinese_failure("translated summary", translated_summary))
        if failures:
            warnings.append(f'Translation skipped "{original_title}": ' + "; ".join(failures))
            continue
        item.title = translated_title
        item.summary = translated_summary
        accepted.append(item)
    items[:] = accepted
    return warnings


STYLE = ":root{--ink:#202420;--muted:#687168;--paper:#f3f0e8;--card:#fffefa;--line:#d9d5ca;--accent:#963e35;--blue:#315f78;--green:#e6eee8;--amber:#f4ead3}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.68 system-ui,-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}.w{max-width:1100px;margin:auto;padding:28px 18px 64px}header{border-bottom:3px solid var(--ink);padding-bottom:18px}.eyebrow{font-size:12px;letter-spacing:.12em;color:var(--muted)}h1{font-size:46px;line-height:1.1;margin:9px 0 12px}.lead{font-size:18px}.stats,nav{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px}.pill,.tag{font-size:12px;padding:3px 9px;border-radius:999px;background:var(--green)}nav{margin:18px 0}nav a{background:#fff;border:1px solid var(--line);border-radius:5px;padding:6px 10px;text-decoration:none}h2{margin-top:36px;border-bottom:1px solid #777;padding-bottom:7px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);padding:16px;border-radius:5px}.card h3{font-size:19px;line-height:1.38;margin:6px 0 8px}.card p{margin:7px 0}.src{font-size:13px;color:var(--muted);margin-top:10px}a{color:var(--blue)}.qa{background:var(--ink);color:#eef2ee;padding:20px;margin-top:40px;border-radius:5px}@media(max-width:760px){h1{font-size:34px}.grid{grid-template-columns:1fr}.w{padding:20px 14px 50px}}"


def render(items: list[Item], now: datetime, output: Path, warnings: list[str]) -> None:
    day = now.astimezone(SGT).date().isoformat()
    sections: dict[str, list[Item]] = {key: [] for key, _ in SECTIONS}
    newest = max(item.published for item in items)
    ranked = sorted(
        items,
        key=lambda x: (ranking_score(x, x.category, newest), x.published, x.title.casefold(), x.url),
        reverse=True,
    )
    # The important list is a view over the already topic-selected pool. It
    # never reintroduces a discarded candidate or triggers extra translation.
    sections["must"] = select_section(ranked, "must", MAX_SECTION_ITEMS)
    important_ids = {id(x) for x in sections["must"]}
    for item in items:
        if id(item) not in important_ids:
            sections[item.category].append(item)
    nav = "".join(f'<a href="#{key}">{html.escape(label)}</a>' for key, label in SECTIONS)
    chunks = [f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Cache-Control" content="no-cache,no-store,must-revalidate"><meta name="brief-version" content="{now.astimezone(SGT).isoformat(timespec="minutes")}"><title>私人 AI 新闻简报｜{day}</title><style>{STYLE}</style></head><body><main class="w">',
              f'<header><div class="eyebrow">PRIVATE INTELLIGENCE BRIEF · ENGLISH SOURCES</div><h1>私人 AI 新闻简报</h1><p class="lead">{day}。自动汇集过去 36 小时的英文新闻；保留高召回结果，并在事件层面合并重复报道。</p><div class="stats"><span class="pill">{len(items)} 件独立事件</span><span class="pill">仅英文信息源</span><span class="pill">更新：{now.astimezone(SGT):%H:%M}</span></div></header><nav>{nav}</nav>']
    for key, label in SECTIONS:
        chunks.append(f'<section id="{key}"><h2>{html.escape(label)}</h2><div class="grid">')
        if not sections[key]:
            chunks.append('<p>本时段未发现通过基本质量与时效检查的新事件。</p>')
        for item in sections[key]:
            summary = item.summary or "Open the source for full details."
            if len(summary) > 520:
                summary = summary[:517].rsplit(" ", 1)[0] + "…"
            links = " · ".join(f'<a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>' for name, url in item.sources)
            category_label = dict(SECTIONS).get(item.category, "其他")
            chunks.append(f'<article class="card"><span class="tag">{html.escape(category_label)}</span><h3>{html.escape(item.title)}</h3><p>{html.escape(summary)}</p><div class="src">来源：{links} · 原文发布时间：{item.published.astimezone(SGT):%Y-%m-%d %H:%M} SGT</div></article>')
        chunks.append('</div></section>')
    warning_text = "；".join(warnings) if warnings else "全部配置来源正常响应。"
    chunks.append(f'<section class="qa" id="qa"><strong>运行质量记录</strong><p>采集 {len(items)} 件去重事件；只使用英文查询与英文来源。日期窗口、链接、重复标题和 HTML 分类结构已自动检查。</p><p>单个来源失败会被跳过，不中断其他来源：{html.escape(warning_text)}</p><p>最后更新：{now.astimezone(SGT):%Y-%m-%d %H:%M}（新加坡时间）</p></section></main></body></html>')
    output.write_text("".join(chunks), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Singapore date (YYYY-MM-DD), primarily for tests")
    parser.add_argument("--fixture", type=Path, help="read a local RSS fixture instead of the network")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--translation-fixture", type=Path, help="local Chinese results used only by deterministic tests")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    if args.date:
        now = datetime.fromisoformat(args.date + "T09:00:00+08:00").astimezone(timezone.utc)
    day = now.astimezone(SGT).date().isoformat()
    cutoff = now - timedelta(hours=36)
    collected: list[Item] = []
    warnings: list[str] = []
    feeds: list[tuple[str, str, str]] = []
    if args.fixture:
        feeds.append(("Fixture", args.fixture.as_uri(), "other"))
    else:
        feeds.extend((name, url, "other") for name, url in DIRECT_FEEDS.items())
        for category, query in QUERIES.items():
            params = urllib.parse.urlencode({"q": f"{query} when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
            feeds.append(("Google News", f"https://news.google.com/rss/search?{params}", category))
    for name, url, hinted in feeds:
        try:
            payload = args.fixture.read_bytes() if args.fixture else fetch(url)
            for item in feed_items(payload, name, now):
                title_lower = item.title.casefold()
                if cutoff <= item.published <= now + timedelta(hours=2) and looks_english(item.title) and not any(term in title_lower for term in LOW_QUALITY):
                    item.category = category_for(item, hinted)
                    collected.append(item)
        except Exception as exc:  # one unavailable publisher must not stop the run
            warnings.append(f"{name}: {type(exc).__name__}")
    candidates = deduplicate(collected)
    if not candidates:
        print("No current items were collected; refusing to replace today's brief.", file=sys.stderr)
        return 1
    # Keep collection broad, but rank and cap each topic before the expensive
    # local Argos pass. A failed translation removes only that selected item.
    items = select_for_translation(candidates)
    try:
        warnings.extend(translate_batch(items, args.translation_fixture))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not items:
        print("No safely translated items remain; refusing to publish an English brief.", file=sys.stderr)
        for warning in warnings:
            print(warning, file=sys.stderr)
        return 1
    output = args.output or Path(f"私人AI新闻简报-{day}.html")
    render(items, now, output, warnings)
    errors = validate_html(output, day)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"date": day, "output": str(output), "events": len(items), "source_failures": warnings}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
