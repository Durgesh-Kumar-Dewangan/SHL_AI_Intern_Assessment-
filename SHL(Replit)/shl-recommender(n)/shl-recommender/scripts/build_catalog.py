"""Cleans a raw SHL catalog scrape into the normalized `app/data/shl_catalog.json`
(and a CSV export) that the service reads at runtime.

We were provided a raw scrape of the SHL Individual Test Solutions catalog
(377 products) rather than needing to scrape https://www.shl.com ourselves.
This script is the documented, re-runnable cleaning pipeline that turns that
raw scrape into the normalized shape the retriever expects:

  - de-duplicates by entity_id
  - drops records missing a name or URL
  - normalizes whitespace/control characters in free-text fields
  - maps the catalog's "keys" taxonomy (e.g. "Personality & Behavior") to the
    single-letter SHL test-type codes used throughout the product catalog
    (A/B/C/D/E/K/P/S)
  - parses a numeric duration_minutes out of the raw duration string where
    possible, for metadata filtering (e.g. "under 10 minutes")
  - coerces adaptive/remote_testing to booleans

Usage:
    python scripts/build_catalog.py --input path/to/raw_scrape.json \
        --output app/data/shl_catalog.json --csv-output app/data/shl_catalog.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

KEY_TO_CODE = {
    "Ability & Aptitude": "A",
    "Biodata & Situational Judgment": "B",
    "Competencies": "C",
    "Development & 360": "D",
    "Assessment Exercises": "E",
    "Knowledge & Skills": "K",
    "Personality & Behavior": "P",
    "Simulations": "S",
}


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = s.replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_duration_minutes(duration_raw: str | None, duration: str | None) -> int | None:
    src = duration_raw or duration or ""
    m = re.search(r"=\s*(\d+)", src)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*minute", duration or "", re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def clean_catalog(raw_items: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    seen_ids: set[str] = set()

    for item in raw_items:
        entity_id = item.get("entity_id")
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)

        name = clean_text(item.get("name"))
        link = clean_text(item.get("link"))
        if not name or not link:
            continue

        keys = item.get("keys") or []
        codes = sorted({KEY_TO_CODE.get(k, "") for k in keys if KEY_TO_CODE.get(k)})
        test_type = ",".join(codes) if codes else "P"

        duration_minutes = parse_duration_minutes(item.get("duration_raw"), item.get("duration"))
        duration_display = clean_text(item.get("duration")) or (
            f"{duration_minutes} minutes" if duration_minutes else "Untimed/Variable"
        )

        cleaned.append(
            {
                "id": entity_id,
                "name": name,
                "url": link,
                "description": clean_text(item.get("description")),
                "duration_minutes": duration_minutes,
                "duration_display": duration_display,
                "adaptive": (item.get("adaptive") or "").strip().lower() == "yes",
                "remote_testing": (item.get("remote") or "").strip().lower() == "yes",
                "languages": [clean_text(l) for l in (item.get("languages") or []) if clean_text(l)],
                "job_levels": [clean_text(j) for j in (item.get("job_levels") or []) if clean_text(j)],
                "keys": keys,
                "test_type": test_type,
                "test_type_codes": codes,
            }
        )
    return cleaned


def write_csv(cleaned: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["id", "name", "url", "test_type", "duration_display", "adaptive", "remote_testing", "languages", "job_levels", "description"]
        )
        for r in cleaned:
            writer.writerow(
                [
                    r["id"],
                    r["name"],
                    r["url"],
                    r["test_type"],
                    r["duration_display"],
                    r["adaptive"],
                    r["remote_testing"],
                    "; ".join(r["languages"]),
                    "; ".join(r["job_levels"]),
                    r["description"][:300],
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to the raw scraped catalog JSON.")
    parser.add_argument("--output", default="app/data/shl_catalog.json")
    parser.add_argument("--csv-output", default="app/data/shl_catalog.csv")
    args = parser.parse_args()

    raw_text = Path(args.input).read_text(encoding="utf-8")
    # strict=False tolerates a small number of unescaped control characters
    # present in the raw scrape's free-text description fields.
    raw_items = json.loads(raw_text, strict=False)

    cleaned = clean_catalog(raw_items)
    print(f"Cleaned {len(cleaned)} / {len(raw_items)} raw records.")

    Path(args.output).write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(cleaned, Path(args.csv_output))
    print(f"Wrote {args.output} and {args.csv_output}")


if __name__ == "__main__":
    main()
