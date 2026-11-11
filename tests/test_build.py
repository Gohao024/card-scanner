"""Run: python3 tests/test_build.py  (uses fake responses, no network)"""
import json
import os
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_prices  # noqa: E402
import build_psa  # noqa: E402

build_prices.SLEEP_SECONDS = 0

CATS = {"results": [
    {"categoryId": 1, "name": "Magic", "displayName": "Magic"},
    {"categoryId": 3, "name": "Pokemon", "displayName": "Pokemon"},
    {"categoryId": 68, "name": "One Piece Card Game", "displayName": "One Piece Card Game"},
    {"categoryId": 85, "name": "Pokemon Japan", "displayName": "Pokemon Japan"},
]}


def products(*rows):
    return {"results": [
        {"productId": pid, "name": name, "extendedData":
            ([{"name": "Number", "displayName": "Card Number", "value": num}] if num else []) +
            ([{"name": "Rarity", "displayName": "Rarity", "value": rar}] if rar else [])}
        for pid, name, num, rar in rows]}


ROUTES = {
    "https://tcgcsv.com/last-updated.txt": "2026-11-11T20:01:00+0000",
    "https://tcgcsv.com/tcgplayer/categories": CATS,
    "https://tcgcsv.com/tcgplayer/3/groups": {"results": [
        {"groupId": 3170, "name": "SWSH12: Silver Tempest", "abbreviation": "SWSH12", "publishedOn": "2022-11-11T00:00:00"},
        {"groupId": 604, "name": "Base Set", "abbreviation": "BS", "publishedOn": "1999-01-09T00:00:00"},
    ]},
    "https://tcgcsv.com/tcgplayer/3/3170/products": products(
        (451396, "Lugia VSTAR", "139/195", "Ultra Rare"),
        (451999, "Silver Tempest Booster Box", None, None)),
    "https://tcgcsv.com/tcgplayer/3/3170/prices": {"results": [
        {"productId": 451396, "lowPrice": 2.5, "midPrice": 3, "highPrice": 9, "marketPrice": 3.104, "subTypeName": "Holofoil"},
        {"productId": 451999, "lowPrice": 150, "marketPrice": 160, "subTypeName": "Normal"}]},
    "https://tcgcsv.com/tcgplayer/3/604/products": products((42382, "Charizard", "4/102", "Holo Rare")),
    "https://tcgcsv.com/tcgplayer/3/604/prices": {"results": [
        {"productId": 42382, "lowPrice": 350, "marketPrice": 400.5, "subTypeName": "Holofoil"},
        {"productId": 42382, "lowPrice": 8000, "marketPrice": None, "subTypeName": "1st Edition Holofoil"}]},
    "https://tcgcsv.com/tcgplayer/85/groups": {"results": []},
    "https://tcgcsv.com/tcgplayer/68/groups": {"results": [
        {"groupId": 23213, "name": "Awakening of the New Era", "abbreviation": "OP05", "publishedOn": "2023-12-08T00:00:00"}]},
    "https://tcgcsv.com/tcgplayer/68/23213/products": products((516002, "Monkey.D.Luffy (Parallel)", "OP05-119", "Secret Rare")),
    "https://tcgcsv.com/tcgplayer/68/23213/prices": {"results": [
        {"productId": 516002, "lowPrice": 170, "marketPrice": 180, "subTypeName": "Normal"}]},
}
calls = []


def fake_get(url, as_json=True, retries=3, timeout=60):
    calls.append(url)
    if url not in ROUTES:
        raise urllib.error.HTTPError(url, 404, "nf", None, None)
    return ROUTES[url]


build_prices.http_get = fake_get


def run_prices(out, **env):
    os.environ.update({"SITE_URL": "", "EVENT": "schedule", "PSA_ONLY": "false", "FORCE": "false", **env})
    sys.argv = ["x", out]
    build_prices.main()


with tempfile.TemporaryDirectory() as d:
    # 1. Fresh build
    run_prices(d)
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert meta["source_updated"] == "2026-11-11T20:01:00+0000"
    assert meta["games"]["pokemon"]["cards"] == 2, meta  # booster box filtered out
    assert meta["games"]["onepiece"]["cards"] == 1
    assert meta["games"]["pokemon-jp"]["cards"] == 0
    pk = json.load(open(os.path.join(d, "pokemon.json")))
    assert pk["sets"][0][1] == "Base Set", "sets sorted oldest first"
    lugia = [c for c in pk["cards"] if c[0] == 451396][0]
    assert lugia[5] == {"Holofoil": [3.1, 2.5]}, lugia
    char = [c for c in pk["cards"] if c[0] == 42382][0]
    assert char[5]["1st Edition Holofoil"] == [None, 8000.0]
    print("ok - fresh price build")

    # 2. Re-use when nothing new upstream: serve the previous build as the "live site"
    for name in ("meta.json", "pokemon.json", "pokemon-jp.json", "onepiece.json"):
        ROUTES[f"https://me.github.io/cards/data/{name}"] = json.load(open(os.path.join(d, name)))
    calls.clear()
    with tempfile.TemporaryDirectory() as d2:
        run_prices(d2, SITE_URL="https://me.github.io/cards")
        assert not any("/tcgplayer/" in u for u in calls), calls
        assert os.path.exists(os.path.join(d2, "onepiece.json"))
    print("ok - re-uses yesterday's data when TCGCSV hasn't changed")

    # 3. A push (PSA link) re-uses even if upstream changed
    ROUTES["https://tcgcsv.com/last-updated.txt"] = "2026-11-12T20:01:00+0000"
    calls.clear()
    with tempfile.TemporaryDirectory() as d3:
        run_prices(d3, SITE_URL="https://me.github.io/cards", EVENT="push")
        assert not any("/tcgplayer/" in u for u in calls)
    print("ok - PSA-link push doesn't re-download prices")

    # 4. Scheduled run with newer upstream downloads again
    calls.clear()
    with tempfile.TemporaryDirectory() as d4:
        run_prices(d4, SITE_URL="https://me.github.io/cards", EVENT="schedule")
        assert any("/tcgplayer/3/604/products" in u for u in calls)
    print("ok - downloads when TCGCSV has new data")

# ---------------- PSA ----------------
psa_calls = []
PSA = {
    "/cert/GetByCertNumber/12345678": {"PSACert": {"CertNumber": "12345678", "SpecID": 99001, "Year": "2022",
                                                   "Brand": "POKEMON SWSH SILVER TEMPEST", "Subject": "LUGIA VSTAR",
                                                   "CardNumber": "139", "Variety": ""}},
    "/pop/GetPSASpecPopulation/99001": {"SpecID": 99001, "Description": "2022 Pokemon Lugia VSTAR",
                                        "PSAPop": {"Total": 5000, "Grade9": 1500, "Grade10": 2500}},
}


def fake_json(url, headers=None, timeout=30):
    psa_calls.append(url)
    if url.startswith(build_psa.PSA_API):
        assert headers["Authorization"] == "Bearer tok"
        path = url[len(build_psa.PSA_API):]
        if path in PSA:
            return PSA[path]
        if path.startswith("/cert/"):
            return {"PSACert": None}
    raise urllib.error.HTTPError(url, 404, "nf", None, None)


build_psa.get_json = fake_json

with tempfile.TemporaryDirectory() as d:
    links = os.path.join(d, "links.json")
    json.dump({"451396": "12345678", "42382": "99999999"}, open(links, "w"))
    os.environ.update({"PSA_TOKEN": "tok", "SITE_URL": "", "PSA_BUDGET": "90"})
    sys.argv = ["x", d, links]
    build_psa.main()
    out = json.load(open(os.path.join(d, "psa.json")))["cards"]
    assert out["451396"]["g9"] == 1500 and out["451396"]["g10"] == 2500 and out["451396"]["spec"] == 99001
    assert "error" in out["42382"], out
    print("ok - PSA cert -> spec -> PSA 9/10 population")

    # Next run: fresh numbers are kept without spending calls; bad cert retried; unlinked card removed.
    os.environ["SITE_URL"] = "https://me.github.io/cards"
    prev = {"cards": out}
    PSA_PREV = "https://me.github.io/cards/data/psa.json"
    orig = build_psa.get_json
    build_psa.get_json = lambda url, headers=None, timeout=30: prev if url == PSA_PREV else orig(url, headers, timeout)
    json.dump({"451396": "12345678"}, open(links, "w"))
    psa_calls.clear()
    build_psa.main()
    out2 = json.load(open(os.path.join(d, "psa.json")))["cards"]
    assert list(out2) == ["451396"] and out2["451396"]["g10"] == 2500
    assert not psa_calls, psa_calls
    print("ok - no PSA calls spent on fresh numbers; unlinked cards dropped")

    # Budget respected
    build_psa.get_json = fake_json
    os.environ.update({"SITE_URL": "", "PSA_BUDGET": "1"})
    json.dump({"451396": "12345678"}, open(links, "w"))
    build_psa.main()
    out3 = json.load(open(os.path.join(d, "psa.json")))["cards"]
    assert "g10" not in out3["451396"]
    print("ok - stops at the call budget and finishes next run")

    # No token: still writes a file
    os.environ["PSA_TOKEN"] = ""
    build_psa.main()
    assert os.path.exists(os.path.join(d, "psa.json"))
    print("ok - works without a PSA token")

print("\nall build tests passed")
