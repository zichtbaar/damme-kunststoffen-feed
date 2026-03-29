#!/usr/bin/env python3
"""
feed_transform.py — WooCommerce XML feed transformer voor Google Shopping
Damme Kunststoffen B.V.

Gebruik:
  python feed_transform.py input/feed.xml output/feed_transformed.xml
  python feed_transform.py input/feed.xml output/feed_transformed.xml --dry-run
  python feed_transform.py input/feed.xml output/feed_transformed.xml --rules rules.json
"""

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime
from xml.etree import ElementTree as ET


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _strip_html(text):
    """Verwijder HTML-tags uit een string."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_price(price_str):
    """
    Geeft float terug of None als prijs leeg/ongeldig is.
    Verwerkt ook price-ranges zoals "149.00-299.00" (neemt eerste waarde).
    """
    if not price_str or price_str.strip() == "":
        return None
    raw = price_str.split("-")[0].strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _format_price(price_str):
    """Zet prijs-string om naar 'X.XX EUR' of '' bij lege prijs."""
    val = _parse_price(price_str)
    if val is None:
        return ""
    return f"{val:.2f} EUR"


def _parse_stock(stock_str):
    """Geeft int terug of 0 bij lege/ongeldige waarde."""
    try:
        return int(stock_str or "0")
    except ValueError:
        return 0


# ── Transformatielogica ───────────────────────────────────────────────────────

def is_maatwerk(name, categories):
    """True als product op maat is."""
    text = (name + " " + categories).lower()
    return "op maat" in text


def determine_category(name, categories, rules):
    """
    Bepaal custom_label_1 op basis van naam + categories.
    Prioriteitsvolgorde: stop bij eerste match.
    """
    text = (name + " " + categories).lower()
    order    = rules.get("category_order", [])
    keywords = rules.get("category_keywords", {})
    for cat in order:
        for kw in keywords.get(cat, []):
            if kw in text:
                return cat
    return "overig"


def determine_custom_label_0(price_str):
    """Prijssegment op basis van prijs."""
    val = _parse_price(price_str)
    if val is None:
        return "op_aanvraag"
    if val < 100:
        return "budget"
    elif val < 500:
        return "midden"
    elif val < 2000:
        return "premium"
    else:
        return "top"


def determine_custom_label_3(stock_str, maatwerk):
    """Voorraadstatus label."""
    if maatwerk:
        return "op_aanvraag"
    stock = _parse_stock(stock_str)
    if stock > 5:
        return "op_voorraad"
    elif stock > 0:
        return "laag_voorraad"
    else:
        return "niet_op_voorraad"


def determine_availability(stock_str, maatwerk):
    """Google availability waarde."""
    if maatwerk:
        return "in_stock"
    stock = _parse_stock(stock_str)
    return "in_stock" if stock > 0 else "out_of_stock"


def determine_google_product_category(category, rules):
    """Google product category ID op basis van custom_label_1."""
    gpc_map = rules.get("google_product_category", {})
    return gpc_map.get(category, "111")


# ── Pipeline ──────────────────────────────────────────────────────────────────

def build_pipeline(item, rules):
    """
    Verwerk één item en geef een gestructureerd resultaat terug.
    Gebruikt door zowel CLI als Streamlit UI.

    Geeft dict terug:
    {
        "sku": str,
        "link": str,
        "display_title": str,
        "display_description": str,
        "price_raw": str,
        "price_formatted": str,      # "X.XX EUR" of ""
        "shopping_eligible": bool,   # False = uitgesloten van Shopping feed
        "is_maatwerk": bool,
        "stock_quantity": int,
        "custom_label_0": str,
        "custom_label_1": str,
        "custom_label_2": str,
        "custom_label_3": str,
        "google_product_category": str,
        "availability": str,
        "steps": [{ nr, label, type, condition, before, after, status }],
        "status": "in_feed" | "excluded_no_price",
    }
    """
    name       = item.findtext("name") or ""
    sku        = item.findtext("sku") or ""
    link       = item.findtext("link") or ""
    price_str  = item.findtext("price") or ""
    stock_str  = item.findtext("stock_quantity") or "0"
    categories = item.findtext("categories") or ""
    raw_desc   = _strip_html(item.findtext("short_description") or "")
    image_url  = item.findtext("image_url") or ""

    maatwerk   = is_maatwerk(name, categories)
    stock      = _parse_stock(stock_str)
    price_val  = _parse_price(price_str)

    steps = []

    # ── Stap 1: Shopping-geschiktheid (prijs) ──────────────────────────────
    if price_val is None or price_val == 0:
        steps.append({
            "nr": 1, "label": "Shopping-check", "type": "exclusion",
            "condition": "Prijs is leeg → uitgesloten van Shopping feed",
            "before": None, "after": None, "status": "excluded",
        })
        # Labels nog steeds berekenen voor overzicht
        cat   = determine_category(name, categories, rules)
        cl0   = "op_aanvraag"
        cl1   = cat
        cl2   = "maatwerk" if maatwerk else "standaard"
        cl3   = determine_custom_label_3(stock_str, maatwerk)
        avail = determine_availability(stock_str, maatwerk)
        gpc   = determine_google_product_category(cat, rules)
        desc  = raw_desc or rules.get("description_fallbacks", {}).get(cat, "")

        return {
            "sku": sku, "link": link, "image_url": image_url,
            "display_title": name, "display_description": desc,
            "price_raw": "", "price_formatted": "",
            "shopping_eligible": False,
            "is_maatwerk": maatwerk, "stock_quantity": stock,
            "custom_label_0": cl0, "custom_label_1": cl1,
            "custom_label_2": cl2, "custom_label_3": cl3,
            "google_product_category": gpc,
            "availability": avail,
            "steps": steps, "status": "excluded_no_price",
        }

    steps.append({
        "nr": 1, "label": "Shopping-check", "type": "exclusion",
        "condition": f"Prijs aanwezig: {price_val:.2f} EUR → opgenomen in Shopping feed",
        "before": None, "after": None, "status": "pass",
    })

    # ── Stap 2: Maatwerk-detectie ──────────────────────────────────────────
    cl2 = "maatwerk" if maatwerk else "standaard"
    steps.append({
        "nr": 2, "label": "Type", "type": "field",
        "condition": '"op maat" gevonden in naam of categorie' if maatwerk else "Geen maatwerk-indicator",
        "before": None, "after": cl2, "status": "added",
    })

    # ── Stap 3: Categorie ──────────────────────────────────────────────────
    cat = determine_category(name, categories, rules)
    steps.append({
        "nr": 3, "label": "Categorie", "type": "field",
        "condition": f"Keyword-match in naam/categories",
        "before": None, "after": cat, "status": "added",
    })

    # ── Stap 4: Labels ─────────────────────────────────────────────────────
    cl0  = determine_custom_label_0(price_str)
    cl1  = cat
    cl3  = determine_custom_label_3(stock_str, maatwerk)
    avail= determine_availability(stock_str, maatwerk)
    gpc  = determine_google_product_category(cat, rules)

    steps.append({
        "nr": 4, "label": "Labels", "type": "labels",
        "condition": "Alle custom labels berekend",
        "before": None,
        "after": f"cl0={cl0}  cl1={cl1}  cl2={cl2}  cl3={cl3}",
        "status": "added",
    })

    # ── Stap 5: Beschrijving ───────────────────────────────────────────────
    desc = raw_desc or rules.get("description_fallbacks", {}).get(cat, "")
    desc_source = "feed" if raw_desc else "fallback"
    steps.append({
        "nr": 5, "label": "Beschrijving", "type": "field",
        "condition": f"Bron: {desc_source}",
        "before": None, "after": desc[:120] + "…" if len(desc) > 120 else desc,
        "status": "added",
    })

    return {
        "sku": sku, "link": link, "image_url": image_url,
        "display_title": name, "display_description": desc,
        "price_raw": price_str, "price_formatted": _format_price(price_str),
        "shopping_eligible": True,
        "is_maatwerk": maatwerk, "stock_quantity": stock,
        "custom_label_0": cl0, "custom_label_1": cl1,
        "custom_label_2": cl2, "custom_label_3": cl3,
        "google_product_category": gpc,
        "availability": avail,
        "steps": steps, "status": "in_feed",
    }


# ── Volledige verwerking ──────────────────────────────────────────────────────

def load_state(state_path="state.json"):
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            return set(json.load(f).get("known_links", []))
    return set()


def save_state(links, state_path="state.json"):
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({
            "last_run": datetime.now().isoformat(),
            "known_links": sorted(links),
        }, f, indent=2)


def process_feed(root, rules, update_state=True, state_path="state.json"):
    """
    Verwerk alle items. Geeft dict terug:
    {
        "results": [pipeline_result, ...],
        "new_links": [str, ...],
        "stats": { label: count, ... },
    }
    """
    known_links   = load_state(state_path)
    items         = root.findall("item")
    current_links = set()
    results       = []
    stats         = {}

    for item in items:
        pr = build_pipeline(item, rules)
        results.append(pr)
        current_links.add(pr["link"])

        cat = pr["custom_label_1"]
        stats[cat] = stats.get(cat, 0) + 1

    new_links = sorted(current_links - known_links) if known_links else []

    if update_state:
        save_state(current_links, state_path)

    return {"results": results, "new_links": new_links, "stats": stats}


# ── Google Shopping feed generator ───────────────────────────────────────────

def generate_google_feed(root, rules):
    """
    Genereer een Google Shopping RSS 2.0 XML met g: namespace.
    Producten zonder prijs worden overgeslagen.
    Geeft een ET.Element (rss) terug.
    """
    gs        = rules.get("google_shopping", {})
    brand     = gs.get("brand", "Damme Kunststoffen")
    condition = gs.get("condition", "new")

    G = "http://base.google.com/ns/1.0"
    ET.register_namespace("g", G)

    rss     = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text       = gs.get("feed_title", "Damme Kunststoffen")
    ET.SubElement(channel, "link").text        = gs.get("channel_link", "https://www.dammekunststoffenwebshop.nl")
    ET.SubElement(channel, "description").text = gs.get("feed_description", "")

    for item in root.findall("item"):
        pr = build_pipeline(item, rules)

        # Producten zonder prijs uitsluiten
        if not pr["shopping_eligible"]:
            continue

        entry = ET.SubElement(channel, "item")

        def g(tag, text):
            el = ET.SubElement(entry, f"{{{G}}}{tag}")
            el.text = text or ""

        g("id",          pr["sku"] or pr["link"])
        g("title",       pr["display_title"][:150])
        g("description", pr["display_description"][:5000])
        g("link",        pr["link"])
        if pr["image_url"]:
            g("image_link", pr["image_url"])
        g("price",              pr["price_formatted"])
        g("availability",       pr["availability"])
        g("brand",              brand)
        g("condition",          condition)
        g("identifier_exists",  gs.get("identifier_exists", "false"))
        g("google_product_category", pr["google_product_category"])
        g("custom_label_0",     pr["custom_label_0"])
        g("custom_label_1",     pr["custom_label_1"])
        g("custom_label_2",     pr["custom_label_2"])
        g("custom_label_3",     pr["custom_label_3"])

    return rss


# ── CLI ───────────────────────────────────────────────────────────────────────

def trunc(text, n=100):
    if not text:
        return "—"
    text = str(text).replace("\n", " ").strip()
    return text[:n] + "…" if len(text) > n else text


def main():
    parser = argparse.ArgumentParser(description="WooCommerce XML feed transformer voor Google Shopping — Damme Kunststoffen")
    parser.add_argument("input",  help="Input XML feed")
    parser.add_argument("output", help="Output Google Shopping XML feed")
    parser.add_argument("--rules",   default="rules.json")
    parser.add_argument("--dry-run", action="store_true", help="Preview, geen output schrijven")
    args = parser.parse_args()

    for path in [args.input, args.rules]:
        if not os.path.exists(path):
            print(f"ERROR: Bestand niet gevonden: {path}", file=sys.stderr)
            sys.exit(1)

    with open(args.rules, encoding="utf-8") as f:
        rules = json.load(f)

    tree = ET.parse(args.input)
    root = tree.getroot()
    data = process_feed(root, rules, update_state=not args.dry_run)

    results = data["results"]
    total   = len(results)
    in_feed = sum(1 for r in results if r["shopping_eligible"])
    excluded= total - in_feed

    print(f"\nFeed: {total} producten  |  {args.input}")
    print(f"In Shopping feed: {in_feed}  |  Uitgesloten (geen prijs): {excluded}")

    if data["new_links"]:
        print(f"\n⚠  {len(data['new_links'])} NIEUWE PRODUCTEN gevonden:")
        for lnk in data["new_links"]:
            print(f"   {lnk}")

    print(f"\n{'─'*65}")
    print(f"{'Categorie':<25} {'Producten':>10}")
    print(f"{'─'*65}")
    for cat, cnt in sorted(data["stats"].items()):
        print(f"{cat:<25} {cnt:>10}")
    print(f"{'─'*65}")

    if args.dry_run:
        print("\nDry-run — geen bestand geschreven.")
    else:
        rss_root = generate_google_feed(root, rules)
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        buf = io.StringIO()
        ET.ElementTree(rss_root).write(buf, encoding="unicode", xml_declaration=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(f"\nOutput geschreven: {args.output}")


if __name__ == "__main__":
    main()
