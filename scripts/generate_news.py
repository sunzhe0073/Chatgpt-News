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

from news_common import SECTIONS, validate_html

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
    score = 2 if any(x in text for x in ("bbc", "ap news", "guardian", "npr", "un news", ".gov", ".int")) else 0
    score += 1 if "reuters" in text else 0
    return score


def deduplicate(items: list[Item]) -> list[Item]:
    groups: list[Item] = []
    for item in sorted(items, key=lambda x: x.published, reverse=True):
        words = canonical_words(item.title)
        match = None
        for existing in groups:
            other = canonical_words(existing.title)
            similarity = len(words & other) / max(1, min(len(words), len(other)))
            if similarity >= 0.72:
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


STYLE = ":root{--ink:#202420;--muted:#687168;--paper:#f3f0e8;--card:#fffefa;--line:#d9d5ca;--accent:#963e35;--blue:#315f78;--green:#e6eee8;--amber:#f4ead3}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.68 system-ui,-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}.w{max-width:1100px;margin:auto;padding:28px 18px 64px}header{border-bottom:3px solid var(--ink);padding-bottom:18px}.eyebrow{font-size:12px;letter-spacing:.12em;color:var(--muted)}h1{font-size:46px;line-height:1.1;margin:9px 0 12px}.lead{font-size:18px}.stats,nav{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px}.pill,.tag{font-size:12px;padding:3px 9px;border-radius:999px;background:var(--green)}nav{margin:18px 0}nav a{background:#fff;border:1px solid var(--line);border-radius:5px;padding:6px 10px;text-decoration:none}h2{margin-top:36px;border-bottom:1px solid #777;padding-bottom:7px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);padding:16px;border-radius:5px}.card h3{font-size:19px;line-height:1.38;margin:6px 0 8px}.card p{margin:7px 0}.src{font-size:13px;color:var(--muted);margin-top:10px}a{color:var(--blue)}.qa{background:var(--ink);color:#eef2ee;padding:20px;margin-top:40px;border-radius:5px}@media(max-width:760px){h1{font-size:34px}.grid{grid-template-columns:1fr}.w{padding:20px 14px 50px}}"


def render(items: list[Item], now: datetime, output: Path, warnings: list[str]) -> None:
    day = now.astimezone(SGT).date().isoformat()
    sections: dict[str, list[Item]] = {key: [] for key, _ in SECTIONS}
    ranked = sorted(items, key=lambda x: (source_score(x.source, x.url), x.published), reverse=True)
    sections["must"] = ranked[: min(10, len(ranked))]
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
            chunks.append(f'<article class="card"><span class="tag">{html.escape(item.category.upper())}</span><h3>{html.escape(item.title)}</h3><p>{html.escape(summary)}</p><div class="src">{item.published.astimezone(SGT):%Y-%m-%d %H:%M} SGT · {links}</div></article>')
        chunks.append('</div></section>')
    warning_text = "；".join(warnings) if warnings else "全部配置来源正常响应。"
    chunks.append(f'<section class="qa" id="qa"><strong>运行质量记录</strong><p>采集 {len(items)} 件去重事件；只使用英文查询与英文来源。日期窗口、链接、重复标题和 HTML 分类结构已自动检查。</p><p>单个来源失败会被跳过，不中断其他来源：{html.escape(warning_text)}</p><p>最后更新：{now.astimezone(SGT):%Y-%m-%d %H:%M}（新加坡时间）</p></section></main></body></html>')
    output.write_text("".join(chunks), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Singapore date (YYYY-MM-DD), primarily for tests")
    parser.add_argument("--fixture", type=Path, help="read a local RSS fixture instead of the network")
    parser.add_argument("--output", type=Path)
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
    items = deduplicate(collected)
    if not items:
        print("No current items were collected; refusing to replace today's brief.", file=sys.stderr)
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
