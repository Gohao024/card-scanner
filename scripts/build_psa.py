#!/usr/bin/env python3
"""Build data/psa.json: PSA 9 and PSA 10 population for the cards in your list.

PSA's free API can't search by card name; it needs PSA's own ID for the card
(the "spec ID"). Every graded slab's cert number leads to that spec ID, so for
each card the app asks about, this script:

  1. searches eBay (official Browse API) for PSA-graded copies of the card,
  2. reads the cert number sellers attach to graded-card listings,
  3. checks that cert with PSA to make sure it's really the same card
     (name, number, English/Japanese, year, reverse holo / 1st edition / parallel),
  4. looks up the PSA 9 and PSA 10 population for that spec.

Cards are found automatically; psa-links.json can still pin a specific cert by
hand if the automatic match is ever wrong.

Inputs (repo root):
  psa-requests.json  {"<key>": {"pid": 123, "game": "pokemon"}} written by the app
  psa-links.json     {"<key>": "<cert number>"} optional manual overrides
  (<key> is the TCGplayer product id, plus "-rev" or "-1st" for those printings)

Env:
  PSA_TOKEN                          PSA API token (GitHub secret)
  EBAY_CLIENT_ID / EBAY_CLIENT_SECRET eBay developer keys (GitHub secrets)
  SITE_URL                           your GitHub Pages address (re-uses the last psa.json)
  PSA_DAILY_LIMIT                    PSA calls allowed per day (default 95; free plan is 100)

Usage: python scripts/build_psa.py site/data [repo_dir]
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PSA_API = "https://api.psacard.com/publicapi"
EBAY_API = "https://api.ebay.com"
EBAY_CCG_CATEGORY = "183454"      # Collectible Card Games > Individual Cards
EBAY_GRADED_CONDITION = "2750"    # "Graded"
REFRESH_AFTER = timedelta(days=7)
RETRY_NOT_FOUND_AFTER = timedelta(days=10)
MAX_CERT_CHECKS_PER_CARD = 3
MAX_EBAY_ITEMS_PER_CARD = 8
UA = "PersonalCardScanner/1.1"

VARIANT_RE = re.compile(r"parallel|alternate|alt art|manga|special|\bsp\b|treasure|serial|super parallel|red super")


class OutOfCalls(Exception):
    pass


def log(*a):
    print(*a, flush=True)


def now():
    return datetime.now(timezone.utc)


def http_json(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def pick(d, *keys):
    if not isinstance(d, dict):
        return None
    low = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low:
            return low[k.lower()]
    return None


# ---------------------------------------------------------------- text helpers
def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def base_name(name):
    s = re.sub(r"\s+-\s+[A-Za-z]*\d[\w/-]*\s*$", "", str(name or ""))
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def variant_text(name):
    return " ".join(a or b for a, b in re.findall(r"\(([^)]*)\)|\[([^\]]*)\]", str(name or ""))).lower()


def bigrams(s):
    s = f" {s} "
    out = {}
    for i in range(len(s) - 1):
        out[s[i:i + 2]] = out.get(s[i:i + 2], 0) + 1
    return out


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    x, y = bigrams(a), bigrams(b)
    inter = sum(min(v, y.get(k, 0)) for k, v in x.items())
    return 2 * inter / (sum(x.values()) + sum(y.values()))


def number_key(num):
    """'025/165' -> '25', 'TG05/TG30' -> '5', 'OP05-119' -> '5119', 'SWSH050' -> '50'."""
    left = str(num or "").split("/")[0]
    return re.sub(r"\D", "", left).lstrip("0")


# ---------------------------------------------------------------- data
def load_cards(data_dir, games):
    cards = {}
    for game in games:
        path = os.path.join(data_dir, f"{game}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            log(f"(no {game}.json; skipping those cards)")
            continue
        sets = data["sets"]
        for pid, name, num, rarity, si, _prices in data["cards"]:
            s = sets[si]
            cards[str(pid)] = {"pid": pid, "game": game, "name": name, "num": num, "rarity": rarity,
                               "set": s[1], "date": s[3]}
    return cards


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or default
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def split_key(key):
    m = re.match(r"^(\d+)(?:-(rev|1st))?$", str(key))
    return (m.group(1), m.group(2) or "") if m else (None, "")


# ---------------------------------------------------------------- PSA
class PSA:
    def __init__(self, token, calls_left):
        self.token = token
        self.calls_left = calls_left
        self.used = 0

    def call(self, path):
        if self.calls_left <= 0:
            raise OutOfCalls("PSA daily limit for this app reached")
        self.calls_left -= 1
        self.used += 1
        try:
            data = http_json(f"{PSA_API}{path}", {"Authorization": f"Bearer {self.token}"})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"PSA rejected the token (HTTP {e.code}). Check the PSA_TOKEN secret.")
            if e.code == 429:
                self.calls_left = 0
                raise OutOfCalls("PSA says the daily limit is reached")
            raise
        time.sleep(0.3)
        return data

    def cert(self, cert):
        c = pick(self.call(f"/cert/GetByCertNumber/{cert}"), "PSACert") or {}
        if not pick(c, "SpecID"):
            return None
        return {
            "spec": int(pick(c, "SpecID")),
            "year": str(pick(c, "Year") or ""),
            "brand": str(pick(c, "Brand") or ""),
            "subject": str(pick(c, "Subject") or ""),
            "number": str(pick(c, "CardNumber") or ""),
            "variety": str(pick(c, "Variety") or ""),
        }

    def population(self, spec):
        data = self.call(f"/pop/GetPSASpecPopulation/{spec}")
        pop = pick(data, "PSAPop") or {}
        return {"g9": pick(pop, "Grade9"), "g10": pick(pop, "Grade10"), "total": pick(pop, "Total")}


def describe(c):
    d = " ".join(x for x in (c["year"], c["brand"], c["subject"]) if x)
    if c["number"]:
        d += f" #{c['number']}"
    if c["variety"]:
        d += f" {c['variety']}"
    return d.strip()


def matches_card(c, card, printing):
    """Does a PSA cert describe this exact TCGplayer card? Returns (ok, reason)."""
    if number_key(c["number"]) != number_key(card["num"]):
        return False, f"number {c['number']} ≠ {card['num']}"
    subj = re.sub(r"^(FA|SR|AR|SAR|CHR|TG|GG|RC)\s*/\s*", "", c["subject"], flags=re.I)
    if similarity(subj, base_name(card["name"])) < 0.5:
        return False, f"name {c['subject']} ≠ {card['name']}"
    jp_psa = "JAPANESE" in c["brand"].upper()
    jp_card = card["game"] == "pokemon-jp"
    if jp_psa != jp_card:
        return False, "language differs"
    m = re.search(r"\d{4}", c["year"])
    if m and card.get("date"):
        if abs(int(m.group(0)) - int(card["date"][:4])) > 1:
            return False, f"year {m.group(0)} vs {card['date'][:4]}"
    variety = (c["variety"] + " " + c["subject"]).upper()
    rev = "REVERSE" in variety
    if (printing == "rev") != rev:
        return False, "reverse holo differs"
    first = "1ST ED" in variety or "1ST EDITION" in c["brand"].upper()
    if (printing == "1st") != first:
        return False, "1st edition differs"
    card_alt = bool(VARIANT_RE.search(variant_text(card["name"])))
    psa_alt = bool(re.search(r"ALT|PARALLEL|MANGA|SPECIAL|\bSP\b|TREASURE|SERIAL", c["variety"].upper()))
    if card["game"] == "onepiece" and card_alt != psa_alt:
        return False, "parallel/alt art differs"
    return True, ""


# ---------------------------------------------------------------- eBay
class Ebay:
    def __init__(self, client_id, client_secret):
        self.id, self.secret = client_id, client_secret
        self.token = None

    def auth(self):
        basic = base64.b64encode(f"{self.id}:{self.secret}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
        try:
            data = http_json(f"{EBAY_API}/identity/v1/oauth2/token",
                             {"Authorization": f"Basic {basic}",
                              "Content-Type": "application/x-www-form-urlencoded"}, data=body)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"eBay rejected the keys (HTTP {e.code}). Check EBAY_CLIENT_ID / EBAY_CLIENT_SECRET.")
        self.token = data["access_token"]

    def get(self, path):
        if not self.token:
            self.auth()
        data = http_json(f"{EBAY_API}{path}", {"Authorization": f"Bearer {self.token}",
                                               "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        time.sleep(0.2)
        return data

    def search(self, query, limit=30):
        params = urllib.parse.urlencode({
            "q": query[:100], "category_ids": EBAY_CCG_CATEGORY,
            "filter": f"conditionIds:{{{EBAY_GRADED_CONDITION}}}", "limit": str(limit),
        })
        return self.get(f"/buy/browse/v1/item_summary/search?{params}").get("itemSummaries", []) or []

    def item(self, item_id):
        return self.get(f"/buy/browse/v1/item/{urllib.parse.quote(item_id, safe='')}")


def certs_from_item(item):
    """PSA cert numbers in an eBay listing (condition descriptors, item specifics, or title)."""
    blob = json.dumps(item).upper()
    if "PSA" not in blob and "PROFESSIONAL SPORTS AUTHENTICATOR" not in blob:
        return []
    found = []
    for d in item.get("conditionDescriptors") or []:
        if "CERT" in str(d.get("name", "")).upper() or str(d.get("name")) == "27503":
            for v in d.get("values") or []:
                for field in ("content", "additionalInfo"):
                    val = v.get(field)
                    vals = val if isinstance(val, list) else [val]
                    for x in vals:
                        found += re.findall(r"\d{7,10}", str(x or ""))
    for a in item.get("localizedAspects") or []:
        if "CERT" in str(a.get("name", "")).upper():
            found += re.findall(r"\d{7,10}", str(a.get("value", "")))
    found += re.findall(r"CERT(?:IFICATION)?\s*(?:#|NO\.?|NUMBER)?\s*:?\s*(\d{7,10})", str(item.get("title", "")).upper())
    out = []
    for c in found:
        if c not in out:
            out.append(c)
    return out


def ebay_queries(card, printing):
    name = base_name(card["name"])
    num = str(card["num"]).split("/")[0]
    extra = []
    v = variant_text(card["name"])
    if card["game"] == "onepiece" and v:
        extra.append(v)
    if printing == "rev":
        extra.append("reverse holo")
    if printing == "1st":
        extra.append("1st edition")
    if card["game"] == "pokemon-jp":
        extra.append("japanese")
    set_name = re.sub(r"^[A-Z0-9]+:\s*", "", card["set"] or "")
    base = f"PSA {name} {num} {' '.join(extra)}".strip()
    return [f"{base} {set_name}".strip(), base]


def title_plausible(title, card):
    t = title.upper()
    if "PSA" not in t:
        return False
    key = number_key(card["num"])
    nums = {number_key(n) for n in re.findall(r"[A-Z]*\d+(?:-\d+)?", t)}
    words = [w for w in norm(base_name(card["name"])).split() if len(w) > 2]
    return key in nums and (not words or any(w.upper() in t for w in words))


def find_spec_via_ebay(ebay, psa, card, printing):
    """Returns (cert, cert_info) or (None, reason)."""
    seen_items, checked = set(), set()
    reasons = []
    for q in ebay_queries(card, printing):
        try:
            results = ebay.search(q)
        except urllib.error.HTTPError as e:
            return None, f"eBay search failed ({e.code})"
        candidates = [r for r in results if r.get("itemId") not in seen_items and title_plausible(r.get("title", ""), card)]
        for r in candidates[:MAX_EBAY_ITEMS_PER_CARD]:
            seen_items.add(r["itemId"])
            try:
                item = ebay.item(r["itemId"])
            except urllib.error.HTTPError:
                continue
            for cert in certs_from_item(item):
                if cert in checked:
                    continue
                if len(checked) >= MAX_CERT_CHECKS_PER_CARD:
                    return None, "; ".join(reasons[-3:]) or "no matching PSA copy"
                checked.add(cert)
                info = psa.cert(cert)
                if not info:
                    reasons.append(f"cert {cert} not found")
                    continue
                ok, why = matches_card(info, card, printing)
                if ok:
                    return cert, info
                reasons.append(f"cert {cert}: {why}")
        if checked:
            break  # the first query already gave real candidates; don't widen
    return None, ("; ".join(reasons[-3:]) if reasons else "no PSA-graded copy with a cert number on eBay right now")


# ---------------------------------------------------------------- main
def age(entry, field="updated"):
    try:
        return now() - datetime.fromisoformat(entry[field])
    except Exception:
        return timedelta(days=9999)


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "site/data"
    repo = sys.argv[2] if len(sys.argv) > 2 else "."
    os.makedirs(data_dir, exist_ok=True)
    site_url = (os.environ.get("SITE_URL") or "").rstrip("/")
    token = (os.environ.get("PSA_TOKEN") or "").strip()
    eb_id = (os.environ.get("EBAY_CLIENT_ID") or "").strip()
    eb_secret = (os.environ.get("EBAY_CLIENT_SECRET") or "").strip()
    daily_limit = int(os.environ.get("PSA_DAILY_LIMIT") or 95)

    requests = read_json(os.path.join(repo, "psa-requests.json"), {})
    links = {str(k): re.sub(r"\D", "", str(v)) for k, v in read_json(os.path.join(repo, "psa-links.json"), {}).items() if v}

    prev = {}
    if site_url:
        try:
            prev = http_json(f"{site_url}/data/psa.json")
        except Exception as e:
            log(f"(no previous psa.json: {e})")
    cards_out = prev.get("cards", {}) if isinstance(prev, dict) else {}
    today = now().strftime("%Y-%m-%d")
    usage = prev.get("usage") if isinstance(prev, dict) else None
    used_today = usage["calls"] if usage and usage.get("date") == today else 0

    wanted = set(requests) | set(links)
    cards_out = {k: v for k, v in cards_out.items() if k in wanted}
    games = {(requests.get(k) or {}).get("game") for k in wanted} | {"pokemon", "pokemon-jp", "onepiece"}
    catalog = load_cards(data_dir, [g for g in games if g])

    if not token:
        log("No PSA_TOKEN secret set; skipping PSA lookups.")
    else:
        psa = PSA(token, max(0, daily_limit - used_today))
        ebay = Ebay(eb_id, eb_secret) if eb_id and eb_secret else None
        if not ebay:
            log("No eBay keys set; only manually linked cards will be looked up.")

        def priority(k):
            e = cards_out.get(k, {})
            manual = k in links and e.get("cert") != links[k]
            if manual or ("g10" not in e and e.get("status") not in ("notfound",)):
                return 0  # new
            if e.get("status") == "notfound":
                return 2 if age(e, "checked") > RETRY_NOT_FOUND_AFTER else 9
            return 1 if age(e) > REFRESH_AFTER else 9

        todo = sorted((k for k in wanted if priority(k) < 9), key=priority)
        log(f"{len(wanted)} cards wanted, {len(todo)} to look up, {psa.calls_left} PSA calls left today")

        try:
            for key in todo:
                pid, printing = split_key(key)
                card = catalog.get(pid or "")
                e = cards_out.setdefault(key, {})
                if not card:
                    e.update({"status": "error", "error": "card not in price data", "checked": now().isoformat(timespec="seconds")})
                    continue
                try:
                    # 1. Which cert / spec?
                    if key in links and e.get("cert") != links[key]:
                        info = psa.cert(links[key])
                        if not info:
                            raise ValueError("that cert number wasn't found at PSA")
                        e.clear()
                        e.update({"cert": links[key], "spec": info["spec"], "certDesc": describe(info), "source": "manual"})
                    elif not e.get("spec"):
                        if not ebay:
                            e.update({"status": "waiting", "checked": now().isoformat(timespec="seconds")})
                            continue
                        cert, info = find_spec_via_ebay(ebay, psa, card, printing)
                        if not cert:
                            e.update({"status": "notfound", "error": info, "checked": now().isoformat(timespec="seconds")})
                            log(f"  {key} {card['name']}: not found ({info})")
                            continue
                        e.update({"cert": cert, "spec": info["spec"], "certDesc": describe(info), "source": "ebay"})
                    # 2. Population
                    pop = psa.population(e["spec"])
                    e.update({k: v for k, v in pop.items() if v is not None})
                    e.update({"status": "ok", "updated": now().isoformat(timespec="seconds"),
                              "checked": now().isoformat(timespec="seconds")})
                    e.pop("error", None)
                    log(f"  {key} {card['name']}: PSA 9={e.get('g9')} PSA 10={e.get('g10')} ({e.get('certDesc')})")
                except OutOfCalls:
                    raise
                except Exception as ex:
                    e.update({"status": "error", "error": str(ex)[:200], "checked": now().isoformat(timespec="seconds")})
                    log(f"  {key}: {ex}")
        except OutOfCalls as q:
            log(f"Stopped: {q}. The rest continue on the next run.")
        used_today += psa.used

    # Anything still not looked up shows as "pending" in the app.
    for key in wanted:
        cards_out.setdefault(key, {"status": "pending"})

    with open(os.path.join(data_dir, "psa.json"), "w", encoding="utf-8") as f:
        json.dump({"built": now().isoformat(timespec="seconds"),
                   "usage": {"date": today, "calls": used_today},
                   "cards": cards_out}, f, ensure_ascii=False, separators=(",", ":"))
    log(f"Wrote psa.json with {len(cards_out)} cards ({used_today} PSA calls used today)")


if __name__ == "__main__":
    main()
