"""Shared constants and validation helpers for the daily news brief."""

from __future__ import annotations

import re
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
    return errors
