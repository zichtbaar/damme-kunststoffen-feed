#!/usr/bin/env python3
"""
Server-side feed refresh script voor Damme Kunststoffen.
Downloadt verse WooCommerce feed, transformeert, en slaat op als Google Shopping XML.
Wordt uitgevoerd via GitHub Actions — output gaat naar docs/ voor GitHub Pages.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import urllib.request
from xml.etree import ElementTree as ET
import json
from feed_transform import process_feed, generate_google_feed

FEED_URL   = "https://www.dammekunststoffenwebshop.nl/products.xml"
RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "docs")
OUTPUT     = os.path.join(OUTPUT_DIR, "google_shopping_feed.xml")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html)"
    )
}

def main():
    print("Feed downloaden...")
    os.makedirs("input", exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    req = urllib.request.Request(FEED_URL, headers=HEADERS)
    with urllib.request.urlopen(req) as response:
        with open("input/feed.xml", "wb") as f:
            f.write(response.read())

    print("Regels laden...")
    with open(RULES_PATH) as f:
        rules = json.load(f)

    print("Feed transformeren...")
    tree = ET.parse("input/feed.xml")
    root = tree.getroot()
    results = process_feed(root, rules, update_state=True)

    print("Google Shopping feed genereren...")
    rss_root = generate_google_feed(root, rules)
    ET.indent(rss_root, space="  ")
    xml_bytes = ET.tostring(rss_root, encoding="unicode", xml_declaration=False)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("<?xml version='1.0' encoding='utf-8'?>\n")
        f.write(xml_bytes)

    stats = results["stats"]
    total = stats.get("transformed", 0) + stats.get("labeled", 0)
    print(f"Klaar! {total} producten verwerkt → {OUTPUT}")

if __name__ == "__main__":
    main()
