# Feed Transformer — Projectstatus voor Claude Code
## Project: Damme Kunststoffen B.V.

## Doel
Python tool + Streamlit UI die de WooCommerce XML feed van **dammekunststoffenwebshop.nl** transformeert
naar een geoptimaliseerd Google Shopping feed-item. Vervangt handmatig werk in Channable.

---

## Architectuur

### Bestanden
```
Damme Kunststoffen/
├── feed_transform.py         CLI script (standalone gebruik)
├── app.py                    Streamlit web UI
├── rules.json                Transformatie- en labelregels
├── state.json                Productstatus vorige run (nieuwe-product detectie)
├── CLAUDE.md                 Dit bestand — projectstatus
├── input/
│   └── feed.xml              Originele WooCommerce XML feed
├── output/
│   └── feed_transformed.xml  Gegenereerde Google Shopping XML output
└── venv/                     Python virtual environment
```

### Starten
```bash
cd ~/Desktop/Damme\ Kunststoffen
venv/bin/streamlit run app.py          # UI starten
python3 feed_transform.py input/feed.xml output/feed_transformed.xml  # CLI
```

---

## XML Feed structuur
- **URL:** https://www.dammekunststoffenwebshop.nl/products.xml
- **Root:** `<root>` → items: `<item>`
- **Velden:** `name`, `short_description`, `link`, `price`, `currency`, `image_url`,
  `sku`, `stock_quantity`, `categories`
- **Prijs:** kan leeg zijn (= prijs op aanvraag / maatwerk) → uitsluiten van Shopping feed
- **Maatwerk-detectie:** "op maat" in `name` of `categories`

---

## Transformatielogica per veld

### 1. title
- Formaat: `[Merk] [Producttype] [Capaciteit of maat] [Materiaal] [Kenmerk]`
- Max 150 tekens. Meest zoekwaardige termen vooraan.
- Merk is altijd **"Damme Kunststoffen"**
- Voorbeeld: `Damme Kunststoffen Septictank 500 liter HDPE Ondergronds IBA Klasse 3`
- Basis: `name` veld uit de feed

### 2. description
- Max 500 tekens. Platte tekst, geen HTML.
- Begin met sterkste USP. Vermeld capaciteit, materiaal, toepassing, call-to-action.
- Basis: `short_description` veld (HTML strippen)

### 3. price
- Leeg → `""` (product uitsluiten van Shopping)
- Gevuld → waarde + `" EUR"` (bijv. `"149.95 EUR"`)

### 4. availability
- `stock_quantity > 0` → `"in_stock"`
- `stock_quantity = 0` → `"out_of_stock"`
- Maatwerk-product → altijd `"in_stock"` (wordt altijd gemaakt)

### 5. identifier_exists
- Altijd `"false"` — Damme Kunststoffen heeft geen GTIN/EAN voor eigen producten

### 6. custom_label_0 — Prijssegment
| Prijs          | Label         |
|----------------|---------------|
| < 100          | `budget`      |
| 100 – 500      | `midden`      |
| 500 – 2000     | `premium`     |
| > 2000         | `top`         |
| leeg           | `op_aanvraag` |

### 7. custom_label_1 — Productcategorie (prioriteitsvolgorde, stop bij eerste match)
Controleer `name` + `categories` (case-insensitive):

| Prioriteit | Label             | Triggertermen                                              |
|------------|-------------------|------------------------------------------------------------|
| 1          | `septictank`      | septic, septictank, iba, riool                             |
| 2          | `afscheider`      | afscheider, vetafscheider, olieafscheider                  |
| 3          | `brandstoftank`   | brandstof, diesel, adblue, mazout                          |
| 4          | `watertank`       | watertank, drinkwater, regenwater                          |
| 5          | `lekbak`          | lekbak, opvangbak                                          |
| 6          | `opslagtank`      | opslagtank                                                 |
| 7          | `plexiglas`       | plexiglas, acrylaat, pmma                                  |
| 8          | `materiaal`       | plaat, buis, staaf, materialen                             |
| 9          | `jerrycan`        | jerrycan, vat, drum                                        |
| 10         | `overig`          | geen van bovenstaande                                      |

### 8. custom_label_2 — Type
- "op maat" in `name` of `categories` → `"maatwerk"`
- Anders → `"standaard"`

### 9. custom_label_3 — Voorraadstatus
| Conditie                          | Label                 |
|-----------------------------------|-----------------------|
| `stock_quantity > 5`              | `op_voorraad`         |
| `stock_quantity` 1–5              | `laag_voorraad`       |
| `stock_quantity = 0` + geen maatwerk | `niet_op_voorraad` |
| maatwerk                          | `op_aanvraag`         |

### 10. google_product_category
- Watertank / opslagtank / septictank / brandstoftank → `"111"`
- Plexiglas / kunststof platen / materialen → `"632"`
- Lekbak / opvangbak → `"111"`
- Afscheider → `"111"`
- Onbekend → `"111"`

---

## Google Shopping feed — veldmapping

| Google veld                  | Bron                                    | Opmerking                              |
|------------------------------|-----------------------------------------|----------------------------------------|
| `g:id`                       | `sku`                                   | Fallback: product-ID uit URL           |
| `g:title`                    | Gegenereerde titel op basis van `name`  | Max 150 tekens                         |
| `g:description`              | Gegenereerde desc op basis van `short_description` | Max 500 tekens, platte tekst |
| `g:link`                     | `link`                                  |                                        |
| `g:image_link`               | `image_url`                             |                                        |
| `g:price`                    | `price`                                 | Leeg = product uitgesloten             |
| `g:availability`             | Berekend (zie §4)                       |                                        |
| `g:brand`                    | `Damme Kunststoffen`                    | Statisch                               |
| `g:condition`                | `new`                                   | Statisch                               |
| `g:identifier_exists`        | `false`                                 | Geen EAN/GTIN                          |
| `g:google_product_category`  | Berekend (zie §10)                      |                                        |
| `g:shipping`                 | NL, prijs op aanvraag                   | Optioneel / te configureren            |
| `g:custom_label_0`           | Prijssegment                            |                                        |
| `g:custom_label_1`           | Productcategorie                        |                                        |
| `g:custom_label_2`           | Type (maatwerk/standaard)               |                                        |
| `g:custom_label_3`           | Voorraadstatus                          |                                        |

---

## UI — Streamlit app (app.py)

Zelfde structuur als kaartenenatlassen.nl tool. Tabs:

1. **Overzicht** — alle producten met labels, filterbaar op categorie/type/voorraad
2. **Google Shopping Preview** — titel + beschrijving per product bekijken
3. **Validatie** — producten zonder prijs, zonder beschrijving, potentiële problemen
4. **Export** — Google Shopping XML downloaden + supplemental CSV

---

## Bekende eigenschappen feed

- Veel maatwerk-producten (geen vaste prijs → uitsluiten)
- Producten zonder `short_description` komen voor → fallback per categorie in `rules.json`
- Geen GTIN/EAN beschikbaar voor eigen producten
- Voorraad kan 0 zijn bij maatwerk → toch `in_stock`

---

## Status (2026-03-29)

### ✅ Gedaan
- CLAUDE.md aangemaakt
- `rules.json` aangemaakt met categorie-regels en beschrijving-fallbacks
- `feed_transform.py` gebouwd (XML parser + transformatielogica)
- Feed getest met live URL: https://www.dammekunststoffenwebshop.nl/products.xml
- **Fix:** Producten met prijs €0,00 uitgesloten van Shopping feed (`price_val == 0` check toegevoegd)
- **Fix:** Categorie `accubak` toegevoegd als aparte categorie (priority 5, vóór lekbak)
  - Keywords: `accubak`
  - Google product category: `111`
  - Fallback beschrijving aanwezig in `rules.json`
  - Doel: aparte Shopping campagne op `custom_label_1 = accubak`

### Feed statistieken (laatste run)
- **Totaal:** 1.884 producten
- **In Shopping feed:** 1.359
- **Uitgesloten (geen prijs):** 525
- **Accubakken:** 58 producten (`custom_label_1 = accubak`)

### 🔄 Volgende stap
- `app.py` bouwen (Streamlit UI, 4 tabs)
- Feed uploaden naar Channable / Google Merchant Center
- 545 NOT_ELIGIBLE producten in Merchant Center oplossen (feed-issue)
- Aparte Shopping campagne aanmaken voor accubakken (`custom_label_1 = accubak`)

### 💡 Toekomstige ideeën
- Claude API-koppeling voor automatisch genereren van titels/beschrijvingen via LLM
- Automatische herkenning van capaciteit (bijv. "500 liter") uit productnaam
- Materiaal-extractie (HDPE, PP, PVC) voor betere titels
