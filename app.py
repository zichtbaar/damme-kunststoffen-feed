import copy
import io
import json
import os
import urllib.request
from xml.etree import ElementTree as ET

import pandas as pd
import streamlit as st

from feed_transform import (
    build_pipeline,
    generate_google_feed,
    load_state,
    process_feed,
    save_state,
    _strip_html,
)

st.set_page_config(
    page_title="Damme Kunststoffen — Feed Transformer",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_rules(path="rules.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def trunc(text, n=80):
    if not text:
        return ""
    text = str(text).replace("\n", " ").strip()
    return text[:n] + "…" if len(text) > n else text


def column_filters(df, key_prefix="cf"):
    """
    Toon filter-inputs boven het dataframe.
    Kolommen met ≤ 12 unieke waarden → multiselect.
    Tekst-kolommen → vrij tekstveld.
    """
    cols = df.columns.tolist()
    filter_cols = st.columns(len(cols))
    mask = pd.Series([True] * len(df), index=df.index)

    for i, col in enumerate(cols):
        unique_vals = df[col].dropna().unique().tolist()
        if 1 < len(unique_vals) <= 12:
            selected = filter_cols[i].multiselect(
                col, options=sorted(unique_vals, key=str),
                default=[], key=f"{key_prefix}_{col}", placeholder="Alle"
            )
            if selected:
                mask &= df[col].isin(selected)
        else:
            val = filter_cols[i].text_input(
                col, value="", key=f"{key_prefix}_{col}", placeholder="Filter…"
            )
            if val:
                mask &= df[col].astype(str).str.contains(val, case=False, na=False)

    return df[mask]


# ── Pipeline stap renderer ────────────────────────────────────────────────────

STEP_ICON = {
    "pass": "✅", "excluded": "🚫", "added": "➕",
    "changed": "✏️", "unchanged": "➖",
}


def render_pipeline(steps):
    for step in steps:
        icon   = STEP_ICON.get(step["status"], "•")
        nr     = step["nr"]
        label  = step["label"]
        cond   = step["condition"]
        stype  = step["type"]
        status = step["status"]

        if stype == "exclusion":
            color = "#f44336" if status == "excluded" else "#4caf50"
            st.html(f"""
            <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #222;font-family:sans-serif">
              <span style="min-width:22px">{icon}</span>
              <div>
                <span style="color:#666;font-size:.72em;text-transform:uppercase;letter-spacing:.05em">stap {nr} · {label.lower()}</span><br>
                <span style="color:{color};font-weight:600">{cond}</span>
              </div>
            </div>""")

        elif stype == "labels":
            st.html(f"""
            <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #222;font-family:sans-serif">
              <span style="min-width:22px">{icon}</span>
              <div>
                <span style="color:#666;font-size:.72em;text-transform:uppercase;letter-spacing:.05em">stap {nr} · labels</span><br>
                <code style="color:#4da6ff;font-size:.85em">{step["after"]}</code>
              </div>
            </div>""")

        elif stype == "field":
            after_col = "#f0a500" if status == "changed" else "#4da6ff"
            st.html(f"""
            <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #222;font-family:sans-serif">
              <span style="min-width:22px">{icon}</span>
              <div style="flex:1;min-width:0">
                <span style="color:#666;font-size:.72em;text-transform:uppercase;letter-spacing:.05em">stap {nr} · {label.lower()}</span>
                <span style="color:#444;font-size:.72em;margin-left:8px">{cond}</span><br>
                <div style="color:{after_col}">{step["after"] or "—"}</div>
              </div>
            </div>""")


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Feed")
    feed_source = st.radio(
        "Bron", ["URL ophalen", "Lokaal bestand", "Upload"],
        label_visibility="collapsed"
    )
    xml_root = None

    if feed_source == "URL ophalen":
        url = st.text_input("URL", value="https://www.dammekunststoffenwebshop.nl/products.xml")
        if st.button("Ophalen", use_container_width=True):
            with st.spinner("Downloaden..."):
                try:
                    with urllib.request.urlopen(url, timeout=30) as r:
                        xml_root = ET.fromstring(r.read())
                    st.session_state["xml_root"] = ET.tostring(xml_root, encoding="unicode")
                    st.success(f"✓ {len(xml_root.findall('item'))} producten")
                except Exception as e:
                    st.error(str(e))
        elif "xml_root" in st.session_state:
            xml_root = ET.fromstring(st.session_state["xml_root"])

    elif feed_source == "Lokaal bestand":
        feed_path = st.text_input("Pad", value="input/feed.xml")
        if os.path.exists(feed_path):
            try:
                xml_root = ET.parse(feed_path).getroot()
                st.success(f"✓ {len(xml_root.findall('item'))} producten geladen")
            except Exception as e:
                st.error(f"XML fout: {e}")
        else:
            st.warning("Bestand niet gevonden")

    else:
        uploaded = st.file_uploader("feed.xml", type=["xml"])
        if uploaded:
            try:
                xml_root = ET.fromstring(uploaded.read())
                st.success(f"✓ {len(xml_root.findall('item'))} producten")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.header("Rules")
    rules_path = st.text_input("rules.json", value="rules.json")
    rules = None
    try:
        rules = load_rules(rules_path)
        categories = rules.get("category_order", []) + ["overig"]
        st.success(f"✓ {len(categories)} categorieën geladen")
        for cat in categories:
            st.caption(f"• {cat}")
    except Exception as e:
        st.error(f"Fout: {e}")
        categories = []


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("Feed Transformer — Damme Kunststoffen")

if xml_root is None or rules is None:
    st.info("Laad een feed en rules.json via de sidebar om te beginnen.")
    st.stop()


@st.cache_data(show_spinner="Feed verwerken...")
def run_pipeline(feed_xml_str, rules_json_str):
    root  = ET.fromstring(feed_xml_str)
    rules = json.loads(rules_json_str)
    return process_feed(root, rules, update_state=False)


data    = run_pipeline(ET.tostring(xml_root, encoding="unicode"), json.dumps(rules))
results = data["results"]

# ── Statistieken ──────────────────────────────────────────────────────────────

total     = len(results)
in_feed   = sum(1 for r in results if r["shopping_eligible"])
excluded  = total - in_feed
maatwerk  = sum(1 for r in results if r["is_maatwerk"])
new_count = len(data["new_links"])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Totaal in feed",         total)
c2.metric("In Shopping feed",       in_feed)
c3.metric("Uitgesloten (geen prijs)", excluded)
c4.metric("Maatwerk producten",     maatwerk)
c5.metric("⚠️ Nieuw" if new_count else "Nieuw", new_count)

# ── Nieuwe producten alert ────────────────────────────────────────────────────

if data["new_links"]:
    with st.expander(f"⚠️ {new_count} nieuwe product(en) gevonden", expanded=True):
        for lnk in data["new_links"]:
            r = next((x for x in results if x["link"] == lnk), None)
            if r:
                st.markdown(
                    f"**{r['sku']}** {r['display_title']}  \n"
                    f"`{lnk}`  \n"
                    f"Categorie: **{r['custom_label_1']}** · Type: {r['custom_label_2']}"
                )
        if st.button("Markeer als gezien"):
            save_state({r["link"] for r in results})
            st.cache_data.clear()
            st.rerun()

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs(["Overzicht", "Google Shopping Preview", "Validatie", "Export"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: OVERZICHT
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1, 1, 2])
    with col_f1:
        sel_cat = st.selectbox(
            "Categorie", ["Alle"] + categories, key="ov_cat"
        )
    with col_f2:
        sel_type = st.selectbox(
            "Type", ["Alle", "maatwerk", "standaard"], key="ov_type"
        )
    with col_f3:
        sel_shop = st.selectbox(
            "In Shopping", ["Alle", "Ja", "Nee"], key="ov_shop"
        )
    with col_f4:
        search = st.text_input(
            "Zoek op naam of SKU", placeholder="bijv. septictank of DAM-001", key="ov_search"
        )

    def filter_results(results, cat, type_, shop, search):
        out = results
        if cat != "Alle":
            out = [r for r in out if r["custom_label_1"] == cat]
        if type_ != "Alle":
            out = [r for r in out if r["custom_label_2"] == type_]
        if shop == "Ja":
            out = [r for r in out if r["shopping_eligible"]]
        elif shop == "Nee":
            out = [r for r in out if not r["shopping_eligible"]]
        if search:
            q = search.lower()
            out = [r for r in out if q in r["display_title"].lower() or q in r["sku"].lower()]
        return out

    filtered = filter_results(results, sel_cat, sel_type, sel_shop, search)
    st.subheader(f"{len(filtered)} product(en)")

    table_rows = []
    for r in filtered:
        table_rows.append({
            "SKU":            r["sku"],
            "Naam":           trunc(r["display_title"], 55),
            "Prijs":          r["price_formatted"] or "op aanvraag",
            "In Shopping":    "✅" if r["shopping_eligible"] else "🚫",
            "Categorie":      r["custom_label_1"],
            "Type":           r["custom_label_2"],
            "Voorraad label": r["custom_label_3"],
            "Availability":   r["availability"],
            "🔗":             r["link"],
        })

    if table_rows:
        df = pd.DataFrame(table_rows)
        with st.expander("Kolom-filters", expanded=False):
            df = column_filters(df, key_prefix="ov_col")
        st.caption(f"{len(df)} product(en) na filters")
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=min(600, 38 + len(df) * 35),
            column_config={
                "SKU":            st.column_config.TextColumn(width="small"),
                "Naam":           st.column_config.TextColumn(width="large"),
                "Prijs":          st.column_config.TextColumn(width="small"),
                "In Shopping":    st.column_config.TextColumn(width="small"),
                "Categorie":      st.column_config.TextColumn(width="medium"),
                "Type":           st.column_config.TextColumn(width="small"),
                "Voorraad label": st.column_config.TextColumn(width="medium"),
                "Availability":   st.column_config.TextColumn(width="small"),
                "🔗":             st.column_config.LinkColumn("🔗", display_text="🔗", width="small"),
            },
        )

    st.divider()
    st.subheader("Pipeline detail")
    detail_search = st.text_input(
        "Selecteer product voor detail", placeholder="SKU of naam"
    )

    if detail_search:
        q = detail_search.lower()
        detail_candidates = [
            r for r in filtered
            if q in r["sku"].lower() or q in r["display_title"].lower()
        ]
    else:
        detail_candidates = filtered[:10]

    if not detail_candidates and detail_search:
        st.info("Geen producten gevonden.")
    elif not detail_search:
        st.caption("Typ een SKU of naam om de pipeline van een specifiek product te zien. Hieronder de eerste 10.")

    for r in detail_candidates[:20]:
        badge = "✅ In Shopping" if r["shopping_eligible"] else "🚫 Geen prijs"
        with st.expander(f"{r['sku']} — {trunc(r['display_title'], 65)}  {badge}"):
            st.caption(f"{r['custom_label_1']} · {r['custom_label_2']} · [{r['link']}]({r['link']})")
            render_pipeline(r["steps"])

    if len(detail_candidates) > 20:
        st.caption(f"+ {len(detail_candidates) - 20} meer — verfijn je zoekopdracht.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: GOOGLE SHOPPING PREVIEW
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("Google Shopping veld-preview")
    st.caption("Zo ziet elk product eruit in de gegenereerde Google Shopping feed. Alleen producten met een prijs worden opgenomen.")

    gs_results = [r for r in results if r["shopping_eligible"]]

    col_g1, col_g2, col_g3 = st.columns([2, 1, 2])
    with col_g1:
        gs_cat    = st.selectbox("Categorie", ["Alle"] + categories, key="gs_cat")
    with col_g2:
        gs_type   = st.selectbox("Type", ["Alle", "maatwerk", "standaard"], key="gs_type")
    with col_g3:
        gs_search = st.text_input("Zoek", placeholder="SKU of naam", key="gs_search")

    if gs_cat != "Alle":
        gs_results = [r for r in gs_results if r["custom_label_1"] == gs_cat]
    if gs_type != "Alle":
        gs_results = [r for r in gs_results if r["custom_label_2"] == gs_type]
    if gs_search:
        q = gs_search.lower()
        gs_results = [r for r in gs_results if q in r["display_title"].lower() or q in r["sku"].lower()]

    preview_rows = []
    for r in gs_results:
        preview_rows.append({
            "g:id":                      r["sku"],
            "g:title":                   trunc(r["display_title"], 80),
            "g:description":             trunc(r["display_description"], 100),
            "🔗":                        r["link"],
            "g:price":                   r["price_formatted"],
            "g:availability":            r["availability"],
            "g:google_product_category": r["google_product_category"],
            "g:custom_label_0":          r["custom_label_0"],
            "g:custom_label_1":          r["custom_label_1"],
            "g:custom_label_2":          r["custom_label_2"],
            "g:custom_label_3":          r["custom_label_3"],
        })

    if preview_rows:
        preview_df = pd.DataFrame(preview_rows)
        with st.expander("Kolom-filters", expanded=False):
            preview_df = column_filters(preview_df, key_prefix="gs_col")
        st.caption(f"{len(preview_df)} producten na filters")
        st.dataframe(
            preview_df,
            use_container_width=True,
            hide_index=True,
            height=min(700, 38 + len(preview_df) * 35),
            column_config={
                "g:id":                      st.column_config.TextColumn(width="small"),
                "g:title":                   st.column_config.TextColumn(width="large"),
                "g:description":             st.column_config.TextColumn(width="large"),
                "🔗":                        st.column_config.LinkColumn("🔗", display_text="🔗", width="small"),
                "g:price":                   st.column_config.TextColumn(width="small"),
                "g:availability":            st.column_config.TextColumn(width="small"),
                "g:google_product_category": st.column_config.TextColumn(width="small"),
                "g:custom_label_0":          st.column_config.TextColumn(width="small"),
                "g:custom_label_1":          st.column_config.TextColumn(width="small"),
                "g:custom_label_2":          st.column_config.TextColumn(width="small"),
                "g:custom_label_3":          st.column_config.TextColumn(width="small"),
            },
        )
    else:
        st.info("Geen producten met prijs gevonden. Controleer de feed.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: VALIDATIE
# ═══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("Feed validatie")

    issues   = []
    warnings = []

    items_map = {
        (item.findtext("link") or ""): item
        for item in xml_root.findall("item")
    }

    for r in results:
        sku   = r["sku"]
        title = r["display_title"]

        # Geen prijs
        if not r["shopping_eligible"]:
            issues.append({
                "SKU":      sku,
                "Probleem": "Geen prijs → uitgesloten van Shopping",
                "Waarde":   r["link"],
            })
            continue

        # Titel te lang
        if len(title) > 150:
            issues.append({
                "SKU":      sku,
                "Probleem": "Titel > 150 tekens",
                "Waarde":   f"{len(title)} tekens: {trunc(title, 60)}",
            })

        # Titel te kort
        if len(title) < 10:
            warnings.append({
                "SKU":          sku,
                "Waarschuwing": "Titel < 10 tekens",
                "Waarde":       title,
            })

        item = items_map.get(r["link"])
        if item is not None:
            # Geen afbeelding
            if not item.findtext("image_url"):
                warnings.append({
                    "SKU":          sku,
                    "Waarschuwing": "Geen afbeelding (image_url)",
                    "Waarde":       "—",
                })

            # Geen beschrijving (en geen fallback)
            if not r["display_description"]:
                warnings.append({
                    "SKU":          sku,
                    "Waarschuwing": "Geen beschrijving en geen fallback",
                    "Waarde":       "—",
                })

            # Niet beschikbaar maar geen maatwerk
            if r["availability"] == "out_of_stock" and not r["is_maatwerk"]:
                warnings.append({
                    "SKU":          sku,
                    "Waarschuwing": "out_of_stock",
                    "Waarde":       f"Voorraad: {r['stock_quantity']}",
                })

    col_v1, col_v2, col_v3 = st.columns(3)
    col_v1.metric("Fouten",                len(issues))
    col_v2.metric("Waarschuwingen",        len(warnings))
    col_v3.metric("Producten gecontroleerd", total)

    if issues:
        st.error(f"**{len(issues)} melding(en)** — producten zonder prijs worden niet opgenomen in Shopping:")
        issues_df = pd.DataFrame(issues)
        with st.expander("Kolom-filters", expanded=False):
            issues_df = column_filters(issues_df, key_prefix="val_issues")
        st.dataframe(issues_df, use_container_width=True, hide_index=True)
    else:
        st.success("Geen kritieke fouten gevonden.")

    if warnings:
        st.warning(f"**{len(warnings)} waarschuwingen** — controleer deze producten:")
        warn_df = pd.DataFrame(warnings)
        with st.expander("Kolom-filters", expanded=False):
            warn_df = column_filters(warn_df, key_prefix="val_warn")
        st.dataframe(warn_df, use_container_width=True, hide_index=True)
    else:
        st.success("Geen waarschuwingen.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.subheader("Export")

    st.markdown(
        f"Feed bevat **{in_feed}** producten in de Shopping feed  "
        f"(van totaal {total}).  "
        f"**{excluded}** producten zonder prijs worden overgeslagen."
    )

    col_e1, col_e2 = st.columns(2)

    with col_e1:
        st.markdown("#### Google Shopping XML")
        st.caption("RSS 2.0 feed met g: namespace, klaar voor upload naar Google Merchant Center.")
        if st.button("Genereer & sla op", type="primary", use_container_width=True):
            if feed_source == "Lokaal bestand" and os.path.exists(feed_path):
                fresh_root = ET.parse(feed_path).getroot()
            else:
                fresh_root = copy.deepcopy(xml_root)

            rss_root = generate_google_feed(fresh_root, rules)

            buf = io.StringIO()
            ET.ElementTree(rss_root).write(buf, encoding="unicode", xml_declaration=True)
            xml_bytes = buf.getvalue().encode("utf-8")

            os.makedirs("output", exist_ok=True)
            output_path = "output/google_shopping_feed.xml"
            with open(output_path, "wb") as f:
                f.write(xml_bytes)

            save_state({r["link"] for r in results})
            st.cache_data.clear()

            st.success(f"✓ Opgeslagen: `{os.path.abspath(output_path)}`")
            st.download_button(
                label="⬇ Download google_shopping_feed.xml",
                data=xml_bytes,
                file_name="google_shopping_feed.xml",
                mime="application/xml",
                use_container_width=True,
            )

    with col_e2:
        st.markdown("#### Supplemental CSV (labels)")
        st.caption("CSV met SKU + alle custom labels, voor gebruik als supplemental feed in Google Merchant Center.")
        if st.button("Genereer CSV", use_container_width=True):
            csv_rows = []
            for r in results:
                if not r["shopping_eligible"]:
                    continue
                csv_rows.append({
                    "id":             r["sku"],
                    "custom_label_0": r["custom_label_0"],
                    "custom_label_1": r["custom_label_1"],
                    "custom_label_2": r["custom_label_2"],
                    "custom_label_3": r["custom_label_3"],
                    "availability":   r["availability"],
                    "price":          r["price_formatted"],
                    "identifier_exists": "false",
                })
            if csv_rows:
                csv_df    = pd.DataFrame(csv_rows)
                csv_bytes = csv_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="⬇ Download supplemental_labels.csv",
                    data=csv_bytes,
                    file_name="supplemental_labels.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

    st.divider()
    st.markdown("#### Feed beschikbaar stellen via ngrok (lokaal testen)")
    with st.expander("Instructies", expanded=False):
        st.markdown("""
**Stap 1 — Feed genereren & opslaan**
Klik hierboven op *Genereer & sla op*.

**Stap 2 — Lokale HTTP-server starten**
```bash
cd ~/Desktop/Damme\\ Kunststoffen
python3 -m http.server 8766 --directory output
```
Feed bereikbaar op: `http://localhost:8766/google_shopping_feed.xml`

**Stap 3 — Publieke URL via ngrok**
```bash
ngrok http 8766
```
Ngrok geeft een publieke URL, bijv: `https://abc123.ngrok-free.app`

Feed-URL voor Merchant Center:
```
https://abc123.ngrok-free.app/google_shopping_feed.xml
```

**Stap 4 — Google Merchant Center**
1. Ga naar [merchants.google.com](https://merchants.google.com)
2. Producten → Feeds → +
3. Land: **Nederland**, taal: **Nederlands**
4. Methode: **Geplande fetch**
5. Plak de ngrok-URL
6. Fetch-interval: dagelijks

> ⚠️ Ngrok-URL verandert bij elke herstart (gratis plan).
""")
