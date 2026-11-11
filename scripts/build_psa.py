#!/usr/bin/env python3
"""Build data/psa.json: PSA 9 and PSA 10 population for the cards you've linked.

PSA's free public API can't search by card name, so each card is linked once
with the cert number of any PSA-graded copy of that exact card (the app writes
these links to psa-links.json as {"<TCGplayer product id>": "<cert number>"}).
This script turns each cert into PSA's spec ID, then looks up the population.

The free PSA plan allows about 100 calls a day, so each run spends at most
PSA_BUDGET calls: new links first, then refreshing the oldest numbers.

Usage: python scripts/build_psa.py site/data
Env:   PSA_TOKEN   your PSA API token (GitHub secret)
       SITE_URL    your GitHub Pages address (to re-use the previous psa.json)
       PSA_BUDGET  max PSA calls per run (default 90)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PSA_API = "https://api.psacard.com/publicapi"
REFRESH_AFTER = timedelta(days=7)


class QuotaExceeded(Exception):
    pass


def log(*args):
    print(*args, flush=True)


def now():
    return datetime.now(timezone.utc)


def get_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "PersonalCardScanner/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def pick(d, *keys):
    """Read a field whether PSA sends it as SpecID, specID or specId."""
    if not isinstance(d, dict):
        return None
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


class PSA:
    def __init__(self, token, budget):
        self.token = token
        self.budget = budget

    def call(self, path):
        if self.budget <= 0:
            raise QuotaExceeded("run budget used up")
        self.budget -= 1
        try:
            data = get_json(f"{PSA_API}{path}", {"Authorization": f"Bearer {self.token}"})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"PSA rejected the token (HTTP {e.code}). Check the PSA_TOKEN secret.")
            if e.code == 429:
                raise QuotaExceeded("PSA daily limit reached")
            raise
        time.sleep(0.3)
        return data

    def spec_for_cert(self, cert):
        data = self.call(f"/cert/GetByCertNumber/{cert}")
        c = pick(data, "PSACert") or {}
        spec = pick(c, "SpecID")
        if not spec:
            raise ValueError("cert not found or has no spec ID")
        parts = [pick(c, "Year"), pick(c, "Brand"), pick(c, "Subject")]
        num = pick(c, "CardNumber")
        variety = pick(c, "Variety")
        desc = " ".join(str(p) for p in parts if p)
        if num:
            desc += f" #{num}"
        if variety:
            desc += f" {variety}"
        return int(spec), desc.strip()

    def population(self, spec):
        data = self.call(f"/pop/GetPSASpecPopulation/{spec}")
        pop = pick(data, "PSAPop") or {}
        return {
            "g9": pick(pop, "Grade9"),
            "g10": pick(pop, "Grade10"),
            "total": pick(pop, "Total"),
            "desc": pick(data, "Description"),
        }


def load_links(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    links = {}
    for pid, cert in (raw or {}).items():
        cert = "".join(ch for ch in str(cert) if ch.isdigit())
        if cert:
            links[str(pid)] = cert
    return links


def load_previous(site_url):
    if not site_url:
        return {}
    try:
        return get_json(f"{site_url}/data/psa.json").get("cards", {})
    except Exception as e:
        log(f"(no previous psa.json: {e})")
        return {}


def age(entry):
    try:
        return now() - datetime.fromisoformat(entry["updated"])
    except Exception:
        return timedelta(days=9999)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "site/data"
    links_path = sys.argv[2] if len(sys.argv) > 2 else "psa-links.json"
    os.makedirs(out_dir, exist_ok=True)
    site_url = (os.environ.get("SITE_URL") or "").rstrip("/")
    token = (os.environ.get("PSA_TOKEN") or "").strip()
    budget = int(os.environ.get("PSA_BUDGET") or 90)

    links = load_links(links_path)
    prev = load_previous(site_url)
    # Keep only cards that are still linked, and drop old data if the cert changed.
    cards = {pid: e for pid, e in prev.items() if pid in links and e.get("cert") == links[pid]}
    for pid, cert in links.items():
        cards.setdefault(pid, {"cert": cert})

    if not token:
        log("No PSA_TOKEN secret set; skipping PSA lookups.")
    else:
        psa = PSA(token, budget)
        # New links first, then the stalest numbers.
        todo = [pid for pid, e in cards.items() if "g10" not in e or e.get("error")]
        todo += sorted((pid for pid, e in cards.items() if pid not in todo and age(e) > REFRESH_AFTER),
                       key=lambda pid: age(cards[pid]), reverse=True)
        log(f"{len(links)} linked cards, {len(todo)} to look up, budget {budget} calls")
        try:
            for pid in todo:
                e = cards[pid]
                try:
                    if not e.get("spec"):
                        e["spec"], e["certDesc"] = psa.spec_for_cert(e["cert"])
                    pop = psa.population(e["spec"])
                    e.update({k: v for k, v in pop.items() if v is not None})
                    e["updated"] = now().isoformat(timespec="seconds")
                    e.pop("error", None)
                    log(f"  {pid}: PSA 9={e.get('g9')} PSA 10={e.get('g10')}")
                except QuotaExceeded:
                    raise
                except Exception as ex:
                    e["error"] = str(ex)[:200]
                    log(f"  {pid}: {ex}")
        except QuotaExceeded as q:
            log(f"Stopped early: {q}. The rest will be done on the next run.")

    with open(os.path.join(out_dir, "psa.json"), "w", encoding="utf-8") as f:
        json.dump({"built": now().isoformat(timespec="seconds"), "cards": cards}, f,
                  ensure_ascii=False, separators=(",", ":"))
    log(f"Wrote psa.json with {len(cards)} cards")


if __name__ == "__main__":
    main()
