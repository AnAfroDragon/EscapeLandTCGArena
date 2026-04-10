#!/usr/bin/env python3
"""Sync Escape Land card data from remote API into EscapeLandCards.json.

Behavior:
- Fetches cards from API_ENDPOINT.
- Transforms cards into EscapeLandCards.json schema.
- Downloads all card images into `images/`.
- Rewrites image URLs to IMAGE_BASE_URL + filename.
- Replaces EscapeLandCards.json with full transformed dataset.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_ENDPOINT = "https://escape-land-promo.com/api/apps/6983607223fa2143ab594a4a/entities/Card"
IMAGE_BASE_URL = "https://anafrodragon.github.io/EscapeLandTCGArena/images/images/"
OUTPUT_JSON = Path("EscapeLandCards.json")
IMAGES_DIR = Path("images")
MAX_WORKERS = 10
TIMEOUT_SECONDS = 30


def normalize_images_dir_casing() -> None:
    entries = set(os.listdir("."))
    if "Images" in entries and "images" not in entries:
        os.rename("Images", "__images_case_tmp__")
        os.rename("__images_case_tmp__", "images")


def fetch_json(url: str) -> List[dict]:
    req = Request(url, headers={"User-Agent": "escape-land-card-sync/1.0"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.load(resp)


def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name:
        raise ValueError(f"Cannot derive filename from URL: {url}")
    return name


def uniquify_key(base: str, seen: Dict[str, int]) -> str:
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base}-{seen[base]}"


def uniquify_filename(name: str, source_url: str, used: Dict[str, str]) -> str:
    if name not in used:
        used[name] = source_url
        return name

    if used[name] == source_url:
        return name

    stem = Path(name).stem
    suffix = Path(name).suffix
    i = 2
    while True:
        candidate = f"{stem}-{i}{suffix}"
        if candidate not in used:
            used[candidate] = source_url
            return candidate
        if used[candidate] == source_url:
            return candidate
        i += 1


def download_image(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": "escape-land-card-sync/1.0"})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        data = resp.read()
    dest.write_bytes(data)


def normalize_cost(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)

    normalize_images_dir_casing()
    cards = fetch_json(API_ENDPOINT)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    seen_ids: Dict[str, int] = {}
    used_filenames: Dict[str, str] = {}
    output: Dict[str, dict] = {}
    downloads: List[Tuple[str, Path]] = []

    for card in cards:
        api_id = str(card.get("id", "")).strip()
        if not api_id:
            continue

        key = uniquify_key(api_id, seen_ids)

        image_url = str(card.get("image_url") or "").strip()
        image_filename = ""
        rewritten_image_url = ""

        if image_url:
            try:
                image_filename = safe_filename_from_url(image_url)
                image_filename = uniquify_filename(image_filename, image_url, used_filenames)
                downloads.append((image_url, IMAGES_DIR / image_filename))
                rewritten_image_url = IMAGE_BASE_URL + image_filename
            except ValueError:
                rewritten_image_url = ""

        cost = normalize_cost(card.get("cost"))
        name = str(card.get("name") or "")
        card_type = str(card.get("card_type") or "")

        traits = card.get("traits")
        if isinstance(traits, list):
            norm_traits = [str(t) for t in traits]
        else:
            norm_traits = []

        entry = {
            "id": key,
            "isToken": False,
            "face": {
                "front": {
                    "name": name,
                    "type": card_type,
                    "cost": cost,
                    "image": rewritten_image_url,
                    "isHorizontal": False,
                }
            },
            "name": name,
            "type": card_type,
            "cost": cost,
            "Traits": norm_traits,
            "Set": "FTM",
        }
        output[key] = entry

    unique_downloads = {}
    for source_url, path in downloads:
        unique_downloads[str(path)] = (source_url, path)

    failures: List[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {
            pool.submit(download_image, source_url, path): (source_url, path)
            for source_url, path in unique_downloads.values()
        }

        for fut in as_completed(future_map):
            source_url, path = future_map[fut]
            try:
                fut.result()
            except Exception as exc:  # pragma: no cover
                failures.append(f"{source_url} -> {path}: {exc}")

    OUTPUT_JSON.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"Fetched cards: {len(cards)}")
    print(f"Written cards: {len(output)}")
    print(f"Images attempted: {len(unique_downloads)}")
    print(f"Images failed: {len(failures)}")
    if failures:
        print("Failed downloads:")
        for line in failures:
            print(f"- {line}")


if __name__ == "__main__":
    main()
