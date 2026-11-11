#!/usr/bin/env python3
"""Build the price files the app reads.

Downloads Pokémon (English + Japanese) and One Piece card data from TCGCSV,
a free daily mirror of TCGplayer's catalog and prices, and writes one compact
JSON file per game plus meta.json into the output folder.

Runs once a day in GitHub Actions. To be polite to TCGCSV (and follow its
rules), it re-uses the copy already on your site whenever TCGCSV hasn't
published anything newer, or when the run was only triggered by a PSA link.

Usage: python scripts/build_prices.py site/data
Env:   SITE_URL   your GitHub Pages address (set by the workflow)
       EVENT      the GitHub event name (schedule, push, workflow_dispatch)
       PSA_ONLY   "true" to skip downloading prices if a previous copy exists
       FORCE      "true" to always download fresh prices
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

TCGCSV = "https://tcgcsv.com"
USER_AGENT = "PersonalCardScanner/1.0"
SLEEP_SECONDS = 0.12  # TCGCSV asks for ~100 ms between requests

# (file key, category names to look for, fallback category id)
GAMES = [
    ("pokemon", ["pokemon"], 3),
    ("pokemon-jp", ["pokemon japan"], 85),
    ("onepiece", ["one piece card game", "one piece"], 68),
]


def log(*args):
    print(*args, flush=True)


def http_get(url, as_json=True, retries=3, timeout=60):
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            time.sleep(SLEEP_SECONDS)
            text = body.decode("utf-8", "replace")
            return json.loads(text, strict=False) if as_json else text
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 404:
                raise
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # network hiccup, bad JSON, timeout
            last_error = e
            time.sleep(3 * (attempt + 1))
    raise last_error


def money(v):
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def fetch_previous(site_url, name):
    """Fetch a file from the copy of the site that's currently live."""
    if not site_url:
        return None
    try:
        return http_get(f"{site_url}/data/{name}", retries=2, timeout=60)
    except Exception as e:
        log(f"  (no previous {name}: {e})")
        return None


def reuse_previous(site_url, prev_meta, out_dir):
    games = (prev_meta or {}).get("games") or {}
    if not games:
        return False
    for key, info in games.items():
        data = fetch_previous(site_url, info["file"])
        if not data:
            return False
        write_json(os.path.join(out_dir, info["file"]), data)
    write_json(os.path.join(out_dir, "meta.json"), prev_meta)
    log("Re-used yesterday's price files from the live site.")
    return True


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def find_category(categories, names, fallback):
    for c in categories:
        for field in ("name", "displayName"):
            if (c.get(field) or "").strip().lower() in names:
                return c["categoryId"]
    return fallback


def build_game(category_id):
    groups = http_get(f"{TCGCSV}/tcgplayer/{category_id}/groups")["results"]
    groups.sort(key=lambda g: (g.get("publishedOn") or "", g.get("groupId") or 0))
    sets, cards, failed = [], [], 0
    for i, g in enumerate(groups, 1):
        gid = g["groupId"]
        try:
            products = http_get(f"{TCGCSV}/tcgplayer/{category_id}/{gid}/products")["results"]
            prices = http_get(f"{TCGCSV}/tcgplayer/{category_id}/{gid}/prices")["results"]
        except Exception as e:
            failed += 1
            log(f"  ! skipped set {gid} ({g.get('name')}): {e}")
            continue

        price_map = {}
        for p in prices:
            printing = p.get("subTypeName") or "Normal"
            price_map.setdefault(p["productId"], {})[printing] = [
                money(p.get("marketPrice")),
                money(p.get("lowPrice")),
            ]

        set_index = None
        for prod in products:
            ext = {e.get("name"): e.get("value") for e in (prod.get("extendedData") or [])}
            number = (ext.get("Number") or "").strip()
            rarity = (ext.get("Rarity") or "").strip()
            if not number and not rarity:
                continue  # sealed product, accessory, etc.
            if set_index is None:
                set_index = len(sets)
                sets.append([gid, g.get("name") or "", g.get("abbreviation") or "",
                             (g.get("publishedOn") or "")[:10]])
            cards.append([prod["productId"], prod.get("name") or "", number, rarity,
                          set_index, price_map.get(prod["productId"], {})])
        if i % 25 == 0:
            log(f"  {i}/{len(groups)} sets…")

    if groups and failed > 0.2 * len(groups):
        raise RuntimeError(f"Too many sets failed to download ({failed}/{len(groups)})")
    return sets, cards


def build_all(out_dir, source_updated):
    categories = http_get(f"{TCGCSV}/tcgplayer/categories")["results"]
    meta = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_updated": source_updated,
        "games": {},
    }
    for key, names, fallback in GAMES:
        cat = find_category(categories, names, fallback)
        log(f"Downloading {key} (category {cat})…")
        sets, cards = build_game(cat)
        fname = f"{key}.json"
        write_json(os.path.join(out_dir, fname), {
            "game": key, "categoryId": cat, "built": meta["built"],
            "sets": sets, "cards": cards,
        })
        meta["games"][key] = {"file": fname, "categoryId": cat, "sets": len(sets), "cards": len(cards)}
        log(f"  {key}: {len(cards)} cards in {len(sets)} sets")
    write_json(os.path.join(out_dir, "meta.json"), meta)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "site/data"
    os.makedirs(out_dir, exist_ok=True)
    site_url = (os.environ.get("SITE_URL") or "").rstrip("/")
    event = os.environ.get("EVENT", "manual")
    psa_only = os.environ.get("PSA_ONLY", "false").lower() == "true"
    force = os.environ.get("FORCE", "false").lower() == "true"

    prev_meta = fetch_previous(site_url, "meta.json")
    try:
        source_updated = http_get(f"{TCGCSV}/last-updated.txt", as_json=False).strip()
    except Exception as e:
        log(f"Could not read TCGCSV last-updated.txt: {e}")
        source_updated = None

    if prev_meta and not force:
        same_source = bool(source_updated) and prev_meta.get("source_updated") == source_updated
        if psa_only or event == "push" or same_source:
            if reuse_previous(site_url, prev_meta, out_dir):
                return
            log("Previous copy unavailable, downloading fresh prices.")

    build_all(out_dir, source_updated)


if __name__ == "__main__":
    main()
