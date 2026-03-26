import requests, json, re, os
from datetime import datetime, timezone
from urllib.parse import quote_plus

API_KEY = os.environ["RAPIDAPI_KEY"]
HEADERS = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "zillow-scraper-api.p.rapidapi.com"
}

EXCLUDED_ZIPS = {"94103", "94105", "94107", "94108", "94110"}

PARKING_CONTEXT = {
    "94109": "Russian Hill/Nob Hill — street parking is competitive; RPP permits cover most blocks.",
    "94114": "Castro — moderate street parking; RPP Zone B. Side streets off Castro St tend to have more availability.",
    "94115": "Pacific Heights/Western Addition — moderate; RPP Zone M. Quieter residential blocks have good availability.",
    "94117": "Haight-Ashbury — competitive near commercial strips; better on outer residential blocks.",
    "94118": "Inner Richmond — generally good residential street parking; RPP Zone K.",
    "94121": "Outer Richmond — good residential street parking; less congested than inner neighborhoods.",
    "94122": "Outer Sunset — good street parking on residential blocks; less congested.",
    "94123": "Marina/Cow Hollow — competitive; RPP permits required evenings. Tough near Chestnut/Union St.",
    "94131": "Glen Park/Noe Valley area — moderate street parking; quieter residential blocks.",
    "94132": "Lake Merced/Lakeshore — good street parking; low-density residential.",
    "94112": "Excelsior — good residential street parking; less congested than central SF.",
    "94134": "Visitacion Valley — good street parking availability.",
    "94124": "Bayview — generally good street parking.",
    "94116": "West Portal/Forest Hill — good residential street parking.",
    "94127": "West Portal area — good residential street parking.",
    "94133": "North Beach/Telegraph Hill — very competitive; street parking is difficult.",
    "94111": "Financial District/Embarcadero — extremely limited street parking.",
    "94102": "Civic Center area — very limited; high theft risk. Garage strongly recommended.",
}


def is_big_complex(listing):
    address = listing.get("address", "")
    detail_url = listing.get("detail_url", "") or ""
    if re.match(r"^[A-Za-z][A-Za-z\s]+,\s+\d+", address):
        return True
    if "/apartments/san-francisco-ca/" in detail_url:
        slug = detail_url.split("/apartments/san-francisco-ca/")[-1].strip("/").split("/")[0]
        if not re.match(r"^\d+", slug):
            return True
    return False


def is_excluded_neighborhood(listing):
    zipcode = str(listing.get("zipcode") or "")
    lat = listing.get("latitude")
    if zipcode in EXCLUDED_ZIPS:
        return True
    if zipcode == "94102" and lat and lat < 37.773:
        return True
    if zipcode == "94109" and lat and lat < 37.793:
        return True
    return False


def fetch_listings():
    all_listings = []
    for page in range(1, 9):
        try:
            resp = requests.get(
                "https://zillow-scraper-api.p.rapidapi.com/zillow/search",
                headers=HEADERS,
                params={
                    "location": "San Francisco, CA",
                    "listing_type": "for_rent",
                    "beds_min": "1",
                    "min_price": "3000",
                    "max_price": "4000",
                    "page": str(page)
                },
                timeout=30
            )
            data = resp.json()
            listings = data.get("data", {}).get("listings", [])
            print(f"Page {page}: {len(listings)} listings")
            if not listings:
                break
            all_listings.extend(listings)
        except Exception as e:
            print(f"Page {page} error: {e}")
            break
    return all_listings


def get_property_details(zpid):
    try:
        resp = requests.get(
            f"https://zillow-scraper-api.p.rapidapi.com/zillow/property/{zpid}",
            headers=HEADERS,
            timeout=30
        )
        data = resp.json()
        return data.get("data", {})
    except Exception as e:
        print(f"  Detail fetch error for {zpid}: {e}")
        return {}


def extract_parking_info(description):
    if not description:
        return None
    keywords = ["garage", "parking", "carport", "driveway", "valet"]
    sentences = re.split(r'(?<=[.!\n])\s*', description)
    hits = []
    for s in sentences:
        s = s.strip()
        if any(k in s.lower() for k in keywords) and 5 < len(s) < 300:
            hits.append(s)
    return " ".join(hits[:2]) if hits else None


def extract_laundry_info(description):
    if not description:
        return None
    keywords = ["laundry", "washer", "dryer", "w/d", "w&d"]
    sentences = re.split(r'(?<=[.!\n])\s*', description)
    hits = []
    for s in sentences:
        s = s.strip()
        if any(k in s.lower() for k in keywords) and 5 < len(s) < 300:
            hits.append(s)
    return " ".join(hits[:2]) if hits else None


def best_match_score(p):
    days = p.get("days_on_zillow") or 99
    price = p.get("price") or 4000
    has_parking = 1 if p.get("_parking_text") else 0
    has_laundry = 1 if p.get("_laundry_text") else 0
    return days * 100 + price / 100 - has_parking * 50 - has_laundry * 20


def days_label(days):
    if days == 0:
        return ("Today", "today")
    elif days == 1:
        return ("Yesterday", "yesterday")
    elif days is not None:
        return (f"{days}d ago", "older")
    return ("Unknown", "older")


# ── Fetch ──────────────────────────────────────────────────────────────────────
print("Fetching listings...")
raw = fetch_listings()
print(f"Total raw: {len(raw)}")

# ── Filter ─────────────────────────────────────────────────────────────────────
candidates = []
for l in raw:
    days = l.get("days_on_zillow")
    if days is None or days > 1:
        continue
    price = l.get("price")
    if price and price > 4000:
        continue
    if is_big_complex(l):
        continue
    if is_excluded_neighborhood(l):
        continue
    candidates.append(l)

print(f"Candidates after filter: {len(candidates)}")

# ── Enrich with details ────────────────────────────────────────────────────────
detailed = []
for l in candidates:
    zpid = l.get("zpid")
    if zpid and not str(zpid).startswith("3"):
        print(f"  Fetching details for {zpid} — {l.get('address', '')}")
        details = get_property_details(zpid)
        merged = {**l, **details}
    else:
        merged = dict(l)

    desc = merged.get("description", "")
    merged["_parking_text"] = extract_parking_info(desc)
    merged["_laundry_text"] = extract_laundry_info(desc)
    zipcode = str(merged.get("zipcode") or "")
    merged["_parking_context"] = PARKING_CONTEXT.get(zipcode)

    price = merged.get("price")
    if price and price > 4000:
        continue

    detailed.append(merged)

print(f"Final listings: {len(detailed)}")

# ── Build card data ────────────────────────────────────────────────────────────
now_str = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

cards_data = []
for p in detailed:
    address_full = p.get("address", "Unknown address")
    city = p.get("city") or "San Francisco"
    state = p.get("state") or "CA"
    zipcode = str(p.get("zipcode") or "")
    maps_query = quote_plus(f"{address_full}, {city}, {state}")
    maps_url = f"https://www.google.com/maps/search/?api=1&query={maps_query}"

    price = p.get("price")
    price_str = f"${price:,.0f}/mo" if isinstance(price, (int, float)) else "Price N/A"

    beds = p.get("bedrooms") or "?"
    baths = p.get("bathrooms") or "?"
    sqft = p.get("living_area_sqft")
    sqft_str = f" &middot; {int(sqft):,} sqft" if isinstance(sqft, (int, float)) else ""

    days = p.get("days_on_zillow")
    days_text, days_cls = days_label(days)

    detail_url = p.get("detail_url") or ""
    if detail_url and not detail_url.startswith("http"):
        detail_url = "https://www.zillow.com" + detail_url

    score = best_match_score(p)

    cards_data.append({
        "score": score,
        "days": days if days is not None else 99,
        "price": price or 0,
        "address": address_full,
        "price_str": price_str,
        "beds": beds,
        "baths": baths,
        "sqft_str": sqft_str,
        "days_text": days_text,
        "days_cls": days_cls,
        "parking_listing": p.get("_parking_text") or "",
        "parking_context": p.get("_parking_context") or "",
        "laundry": p.get("_laundry_text") or "",
        "zillow_url": detail_url,
        "maps_url": maps_url,
    })

cards_json = json.dumps(cards_data, ensure_ascii=False)
count = len(cards_data)

# ── Write HTML ─────────────────────────────────────────────────────────────────
html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SF Rentals &mdash; Fresh Listings</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; color: #333; }
    header { background: #1a1a2e; color: white; padding: 1.5rem 2rem; }
    header h1 { font-size: 1.4rem; font-weight: 700; }
    header p { font-size: 0.82rem; opacity: 0.65; margin-top: 0.3rem; }
    .criteria { background: #16213e; color: #8899bb; font-size: 0.78rem; padding: 0.5rem 2rem; }
    .toolbar { background: white; border-bottom: 1px solid #e5e7eb; padding: 0.6rem 1.5rem; display: flex; align-items: center; gap: 0.75rem; }
    .toolbar span { font-size: 0.82rem; color: #666; }
    .sort-btn { border: 1px solid #d1d5db; background: white; color: #374151; padding: 0.3rem 0.85rem; border-radius: 20px; font-size: 0.8rem; cursor: pointer; transition: all .15s; }
    .sort-btn:hover { background: #f3f4f6; }
    .sort-btn.active { background: #1a1a2e; color: white; border-color: #1a1a2e; }
    .container { max-width: 860px; margin: 1.5rem auto; padding: 0 1rem; }
    .count { font-size: 0.85rem; color: #888; margin-bottom: 1rem; }
    .card { background: white; border-radius: 10px; padding: 1.1rem 1.4rem; margin-bottom: 0.85rem; box-shadow: 0 1px 3px rgba(0,0,0,0.07); }
    .card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
    .address { font-weight: 600; font-size: 0.97rem; }
    .meta { font-size: 0.82rem; color: #777; margin-top: 0.2rem; }
    .right { text-align: right; flex-shrink: 0; }
    .price { font-size: 1.15rem; font-weight: 700; color: #16a34a; }
    .badge { display: inline-block; font-size: 0.68rem; font-weight: 600; padding: 0.18rem 0.5rem; border-radius: 4px; margin-top: 0.25rem; }
    .today { background: #dcfce7; color: #166534; }
    .yesterday { background: #fef9c3; color: #854d0e; }
    .older { background: #f1f5f9; color: #64748b; }
    .divider { border: none; border-top: 1px solid #f1f5f9; margin: 0.8rem 0; }
    .info-row { display: flex; gap: 0.5rem; align-items: flex-start; margin-top: 0.5rem; font-size: 0.82rem; }
    .info-label { font-weight: 600; color: #374151; flex-shrink: 0; width: 90px; }
    .info-text { color: #555; line-height: 1.45; }
    .no-info { color: #bbb; font-style: italic; }
    .actions { display: flex; gap: 0.6rem; margin-top: 0.9rem; flex-wrap: wrap; }
    .btn { display: inline-flex; align-items: center; gap: 0.35rem; text-decoration: none; padding: 0.4rem 0.85rem; border-radius: 6px; font-size: 0.78rem; font-weight: 500; }
    .btn-zillow { background: #1a1a2e; color: white; }
    .btn-maps { background: #fff; color: #374151; border: 1px solid #d1d5db; }
    .btn:hover { opacity: 0.82; }
    .empty { text-align: center; padding: 3rem; color: #999; background: white; border-radius: 10px; font-size: 0.9rem; }
  </style>
</head>
<body>
  <header>
    <h1>SF Rentals &mdash; Fresh Listings</h1>
    <p>Updated: UPDATED_TIME</p>
  </header>
  <div class="criteria">1 bed min &nbsp;&middot;&nbsp; $3,000&ndash;$4,000/mo &nbsp;&middot;&nbsp; Listed in last 24h &nbsp;&middot;&nbsp; Individual listings only &nbsp;&middot;&nbsp; No Nob Hill / Tenderloin / Mission / SOMA</div>
  <div class="toolbar">
    <span>Sort by:</span>
    <button class="sort-btn active" onclick="sortBy('recent',this)">Recently Listed</button>
    <button class="sort-btn" onclick="sortBy('best',this)">Best Match</button>
    <button class="sort-btn" onclick="sortBy('price',this)">Price: Low to High</button>
  </div>
  <div class="container">
    <p class="count" id="count">COUNT_PLACEHOLDER</p>
    <div id="cards"></div>
  </div>
  <script>
    const DATA = CARDS_JSON_PLACEHOLDER;

    function sortBy(mode, btn) {
      document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      render(mode);
    }

    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function render(mode) {
      const sorted = [...DATA];
      if (mode === 'recent') sorted.sort((a,b) => a.days - b.days || a.price - b.price);
      else if (mode === 'best') sorted.sort((a,b) => a.score - b.score);
      else if (mode === 'price') sorted.sort((a,b) => a.price - b.price);

      const el = document.getElementById('cards');
      if (!sorted.length) {
        el.innerHTML = '<div class="empty">No listings found matching your criteria right now. Check back soon &mdash; page refreshes every hour.</div>';
        return;
      }

      el.innerHTML = sorted.map(p => {
        const pListing = p.parking_listing
          ? `<div class="info-row"><span class="info-label">Parking</span><span class="info-text">${esc(p.parking_listing)}</span></div>`
          : `<div class="info-row"><span class="info-label">Parking</span><span class="info-text no-info">Not mentioned in listing</span></div>`;
        const pCtx = p.parking_context
          ? `<div class="info-row"><span class="info-label">Neighborhood</span><span class="info-text">${esc(p.parking_context)}</span></div>`
          : '';
        const laundry = p.laundry
          ? `<div class="info-row"><span class="info-label">Laundry</span><span class="info-text">${esc(p.laundry)}</span></div>`
          : `<div class="info-row"><span class="info-label">Laundry</span><span class="info-text no-info">Not mentioned in listing</span></div>`;
        const zBtn = p.zillow_url
          ? `<a href="${esc(p.zillow_url)}" target="_blank" class="btn btn-zillow">View on Zillow</a>`
          : '';
        const mBtn = `<a href="${esc(p.maps_url)}" target="_blank" class="btn btn-maps"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="flex-shrink:0"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>Google Maps</a>`;
        return `<div class="card">
  <div class="card-top">
    <div><div class="address">${esc(p.address)}</div><div class="meta">${esc(p.beds)} bed &middot; ${esc(p.baths)} bath${p.sqft_str}</div></div>
    <div class="right"><div class="price">${esc(p.price_str)}</div><span class="badge ${p.days_cls}">${esc(p.days_text)}</span></div>
  </div>
  <hr class="divider">
  ${pListing}${pCtx}${laundry}
  <div class="actions">${zBtn}${mBtn}</div>
</div>`;
      }).join('');
    }

    render('recent');
  </script>
</body>
</html>"""

html = html.replace("UPDATED_TIME", now_str)
html = html.replace("COUNT_PLACEHOLDER", f"{count} listing{'s' if count != 1 else ''} found")
html = html.replace("CARDS_JSON_PLACEHOLDER", cards_json)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("index.html written successfully")
