#!/usr/bin/env python3
import argparse
from pathlib import Path

from news_common import validate_html

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
parser.add_argument("--date", required=True)
args = parser.parse_args()
errors = validate_html(args.path, args.date)
if errors:
    raise SystemExit("\n".join(errors))
print(
    f"Validated {args.path}: date, links, event counts, Chinese text, "
    "duplicates, and section structure OK"
)
