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

REPO = "richinroygeorge/rich"


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


def build_card(p):
    address_full = p.get("address", "Unknown address")
    city = p.get("city") or "San Francisco"
    state = p.get("state") or "CA"
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
    zpid = str(p.get("zpid") or "")
    uid = zpid if zpid and not zpid.startswith("3") else re.sub(r"[^a-z0-9]", "", address_full.lower())[:40]
    return {
        "uid": uid,
        "score": best_match_score(p),
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
    }


# ── Load saved favorites from repo ────────────────────────────────────────────
saved = []
if os.path.exists("favorites.json"):
    try:
        with open("favorites.json") as f:
            saved = json.load(f)
        print(f"Loaded {len(saved)} saved favorites")
    except Exception as e:
        print(f"Could not load favorites.json: {e}")

saved_uids = {s["uid"] for s in saved if "uid" in s}

# ── Fetch fresh listings ───────────────────────────────────────────────────────
print("Fetching listings...")
raw = fetch_listings()
print(f"Total raw: {len(raw)}")

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

print(f"Final fresh listings: {len(detailed)}")

cards_data = [build_card(p) for p in detailed]
# Mark which fresh listings are already saved
fresh_uids = {c["uid"] for c in cards_data}
for c in cards_data:
    c["saved"] = c["uid"] in saved_uids

# Saved listings that aren't in fresh results (older, still show them)
saved_only = [s for s in saved if s.get("uid") not in fresh_uids]

cards_json = json.dumps(cards_data, ensure_ascii=False)
saved_json = json.dumps(saved, ensure_ascii=False)
now_str = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
count = len(cards_data)
saved_count = len(saved)

# ── HTML ───────────────────────────────────────────────────────────────────────
html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SF Rentals &mdash; Fresh Listings</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; color: #333; }
    header { background: #1a1a2e; color: white; padding: 1.5rem 2rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; }
    header h1 { font-size: 1.4rem; font-weight: 700; }
    header p { font-size: 0.82rem; opacity: 0.65; margin-top: 0.2rem; }
    .criteria { background: #16213e; color: #8899bb; font-size: 0.78rem; padding: 0.5rem 2rem; }
    .tabs { background: white; border-bottom: 1px solid #e5e7eb; display: flex; align-items: center; gap: 0; padding: 0 1.5rem; }
    .tab { padding: 0.7rem 1.1rem; font-size: 0.85rem; font-weight: 500; cursor: pointer; border-bottom: 2px solid transparent; color: #6b7280; background: none; border-top: none; border-left: none; border-right: none; }
    .tab.active { color: #1a1a2e; border-bottom-color: #1a1a2e; }
    .tab .badge { display: inline-block; background: #f1f5f9; color: #64748b; font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 10px; margin-left: 0.3rem; font-weight: 600; }
    .tab.active .badge { background: #1a1a2e; color: white; }
    .toolbar { background: white; border-bottom: 1px solid #f1f5f9; padding: 0.5rem 1.5rem; display: flex; align-items: center; gap: 0.6rem; }
    .toolbar span { font-size: 0.8rem; color: #888; }
    .sort-btn { border: 1px solid #e5e7eb; background: white; color: #374151; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.78rem; cursor: pointer; }
    .sort-btn.active { background: #1a1a2e; color: white; border-color: #1a1a2e; }
    .container { max-width: 860px; margin: 1.25rem auto; padding: 0 1rem; }
    .section-header { font-size: 0.85rem; color: #888; margin-bottom: 0.85rem; }
    .card { background: white; border-radius: 10px; padding: 1.1rem 1.4rem; margin-bottom: 0.75rem; box-shadow: 0 1px 3px rgba(0,0,0,0.07); }
    .card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
    .address { font-weight: 600; font-size: 0.97rem; padding-right: 2rem; }
    .meta { font-size: 0.82rem; color: #777; margin-top: 0.2rem; }
    .right { text-align: right; flex-shrink: 0; }
    .price { font-size: 1.15rem; font-weight: 700; color: #16a34a; }
    .badge-age { display: inline-block; font-size: 0.68rem; font-weight: 600; padding: 0.18rem 0.5rem; border-radius: 4px; margin-top: 0.25rem; }
    .today { background: #dcfce7; color: #166534; }
    .yesterday { background: #fef9c3; color: #854d0e; }
    .older { background: #f1f5f9; color: #64748b; }
    .divider { border: none; border-top: 1px solid #f1f5f9; margin: 0.75rem 0; }
    .info-row { display: flex; gap: 0.5rem; align-items: flex-start; margin-top: 0.45rem; font-size: 0.82rem; }
    .info-label { font-weight: 600; color: #374151; flex-shrink: 0; width: 90px; }
    .info-text { color: #555; line-height: 1.45; }
    .no-info { color: #ccc; font-style: italic; }
    .actions { display: flex; gap: 0.5rem; margin-top: 0.85rem; flex-wrap: wrap; align-items: center; }
    .btn { display: inline-flex; align-items: center; gap: 0.3rem; text-decoration: none; padding: 0.38rem 0.8rem; border-radius: 6px; font-size: 0.78rem; font-weight: 500; border: none; cursor: pointer; }
    .btn-zillow { background: #1a1a2e; color: white; }
    .btn-maps { background: #fff; color: #374151; border: 1px solid #d1d5db; }
    .btn:hover { opacity: 0.82; }
    .fav-btn { background: none; border: none; cursor: pointer; font-size: 1.3rem; line-height: 1; padding: 0.1rem; color: #d1d5db; transition: color .15s, transform .1s; margin-left: auto; }
    .fav-btn:hover { transform: scale(1.2); }
    .fav-btn.saved { color: #f59e0b; }
    .empty { text-align: center; padding: 2.5rem; color: #aaa; background: white; border-radius: 10px; font-size: 0.88rem; line-height: 1.6; }
    .saved-badge { display: inline-block; background: #fef9c3; color: #92400e; font-size: 0.68rem; font-weight: 600; padding: 0.15rem 0.45rem; border-radius: 4px; margin-left: 0.4rem; vertical-align: middle; }
    .token-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100; align-items: center; justify-content: center; }
    .token-modal.show { display: flex; }
    .token-box { background: white; border-radius: 12px; padding: 1.5rem; max-width: 420px; width: 90%; }
    .token-box h3 { font-size: 1rem; margin-bottom: 0.5rem; }
    .token-box p { font-size: 0.82rem; color: #666; margin-bottom: 1rem; line-height: 1.5; }
    .token-box input { width: 100%; border: 1px solid #d1d5db; border-radius: 6px; padding: 0.5rem 0.75rem; font-size: 0.85rem; margin-bottom: 0.75rem; font-family: monospace; }
    .token-box-btns { display: flex; gap: 0.5rem; justify-content: flex-end; }
    .toast { position: fixed; bottom: 1.5rem; left: 50%; transform: translateX(-50%); background: #1a1a2e; color: white; padding: 0.6rem 1.2rem; border-radius: 8px; font-size: 0.82rem; opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 200; }
    .toast.show { opacity: 1; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>SF Rentals &mdash; Fresh Listings</h1>
      <p>Updated: UPDATED_TIME</p>
    </div>
  </header>
  <div class="criteria">1 bed min &nbsp;&middot;&nbsp; $3,000&ndash;$4,000/mo &nbsp;&middot;&nbsp; Listed in last 24h &nbsp;&middot;&nbsp; Individual listings only &nbsp;&middot;&nbsp; No Nob Hill / Tenderloin / Mission / SOMA</div>

  <div class="tabs">
    <button class="tab active" onclick="showTab('fresh',this)">Fresh Listings <span class="badge" id="fresh-count">COUNT_PLACEHOLDER</span></button>
    <button class="tab" onclick="showTab('saved',this)">Saved <span class="badge" id="saved-count">SAVED_COUNT</span></button>
  </div>

  <div id="tab-fresh">
    <div class="toolbar">
      <span>Sort:</span>
      <button class="sort-btn active" onclick="sortBy('recent',this)">Recently Listed</button>
      <button class="sort-btn" onclick="sortBy('best',this)">Best Match</button>
      <button class="sort-btn" onclick="sortBy('price',this)">Price &uarr;</button>
    </div>
    <div class="container">
      <div id="fresh-cards"></div>
    </div>
  </div>

  <div id="tab-saved" style="display:none">
    <div class="container" style="margin-top:1.25rem">
      <div id="saved-cards"></div>
    </div>
  </div>

  <div class="token-modal" id="tokenModal">
    <div class="token-box">
      <h3>Enter your GitHub token to save</h3>
      <p>Your token needs <code>repo</code> scope for <strong>richinroygeorge/rich</strong>. It's stored only in this browser session &mdash; never sent anywhere except GitHub.</p>
      <input type="password" id="tokenInput" placeholder="ghp_..." />
      <div class="token-box-btns">
        <button class="btn btn-maps" onclick="closeModal()">Cancel</button>
        <button class="btn btn-zillow" onclick="submitToken()">Save &amp; Continue</button>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    const FRESH = CARDS_JSON_PLACEHOLDER;
    const REPO = "richinroygeorge/rich";
    const FAV_URL = `https://raw.githubusercontent.com/${REPO}/main/favorites.json`;

    // In-memory favorites map: uid -> card object
    let favMap = {};
    let pendingFavUid = null;

    function getToken() { return sessionStorage.getItem('gh_token'); }

    // Load favorites live from the repo on every page load
    async function loadFavorites() {
      try {
        const resp = await fetch(FAV_URL + '?t=' + Date.now());
        const data = await resp.json();
        favMap = {};
        data.forEach(s => { if (s.uid) favMap[s.uid] = s; });
      } catch(e) {
        // fallback: mark any fresh listings that were saved at generation time
        FRESH.forEach(c => { if (c.saved) favMap[c.uid] = c; });
      }
      renderFresh('recent');
      updateSavedBadge();
    }

    function showTab(tab, btn) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-fresh').style.display = tab === 'fresh' ? '' : 'none';
      document.getElementById('tab-saved').style.display = tab === 'saved' ? '' : 'none';
      if (tab === 'saved') renderSaved();
    }

    function sortBy(mode, btn) {
      document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderFresh(mode);
    }

    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function cardHTML(p, inSavedTab) {
      const isSaved = !!favMap[p.uid];
      const favCls = isSaved ? 'saved' : '';
      const favTitle = isSaved ? 'Remove from saved' : 'Save listing';
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
      const mBtn = `<a href="${esc(p.maps_url)}" target="_blank" class="btn btn-maps"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="flex-shrink:0"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>Maps</a>`;
      const savedLabel = inSavedTab && !FRESH.find(f => f.uid === p.uid) ? '<span class="saved-badge">Saved</span>' : '';
      return `<div class="card" id="card-${esc(p.uid)}">
  <div class="card-top">
    <div><div class="address">${esc(p.address)}${savedLabel}</div><div class="meta">${esc(String(p.beds))} bed &middot; ${esc(String(p.baths))} bath${p.sqft_str}</div></div>
    <div class="right"><div class="price">${esc(p.price_str)}</div><span class="badge-age ${p.days_cls}">${esc(p.days_text)}</span></div>
  </div>
  <hr class="divider">
  ${pListing}${pCtx}${laundry}
  <div class="actions">${zBtn}${mBtn}<button class="fav-btn ${favCls}" onclick="toggleFav('${esc(p.uid)}')" title="${favTitle}">&#9733;</button></div>
</div>`;
    }

    function renderFresh(mode) {
      mode = mode || 'recent';
      const sorted = [...FRESH];
      if (mode === 'recent') sorted.sort((a,b) => a.days - b.days || a.price - b.price);
      else if (mode === 'best') sorted.sort((a,b) => a.score - b.score);
      else sorted.sort((a,b) => a.price - b.price);
      const el = document.getElementById('fresh-cards');
      el.innerHTML = sorted.length
        ? sorted.map(p => cardHTML(p, false)).join('')
        : '<div class="empty">No listings found right now matching your criteria.<br>Check back soon &mdash; this page refreshes every hour.</div>';
    }

    function renderSaved() {
      const all = Object.values(favMap);
      const el = document.getElementById('saved-cards');
      if (!all.length) {
        el.innerHTML = '<div class="empty">No saved listings yet.<br>Click the &#9733; on any listing to save it here permanently.</div>';
        return;
      }
      el.innerHTML = all.map(p => cardHTML(p, true)).join('');
      document.getElementById('saved-count').textContent = all.length;
    }

    function updateSavedBadge() {
      const n = Object.keys(favMap).length;
      document.getElementById('saved-count').textContent = n;
    }

    function toggleFav(uid) {
      const card = FRESH.find(c => c.uid === uid) || favMap[uid];
      if (!card) return;
      if (favMap[uid]) {
        // Remove
        delete favMap[uid];
        persistFavorites();
      } else {
        // Add — need token
        if (!getToken()) {
          pendingFavUid = uid;
          document.getElementById('tokenModal').classList.add('show');
          return;
        }
        favMap[uid] = card;
        persistFavorites();
      }
      refreshCardButtons();
      updateSavedBadge();
    }

    function refreshCardButtons() {
      document.querySelectorAll('.card').forEach(el => {
        const uid = el.id.replace('card-','');
        const btn = el.querySelector('.fav-btn');
        if (!btn) return;
        if (favMap[uid]) {
          btn.classList.add('saved');
          btn.title = 'Remove from saved';
        } else {
          btn.classList.remove('saved');
          btn.title = 'Save listing';
        }
      });
    }

    function closeModal() {
      document.getElementById('tokenModal').classList.remove('show');
      document.getElementById('tokenInput').value = '';
      pendingFavUid = null;
    }

    function submitToken() {
      const tok = document.getElementById('tokenInput').value.trim();
      if (!tok) return;
      sessionStorage.setItem('gh_token', tok);
      closeModal();
      if (pendingFavUid) {
        const card = FRESH.find(c => c.uid === pendingFavUid) || favMap[pendingFavUid];
        if (card) { favMap[pendingFavUid] = card; }
        pendingFavUid = null;
        persistFavorites();
        refreshCardButtons();
        updateSavedBadge();
      }
    }

    async function persistFavorites() {
      const token = getToken();
      if (!token) return;
      const favorites = Object.values(favMap);
      try {
        // Get current SHA
        const meta = await fetch(`https://api.github.com/repos/${REPO}/contents/favorites.json`, {
          headers: { 'Authorization': `token ${token}` }
        });
        const metaJson = await meta.json();
        const sha = metaJson.sha;
        const content = btoa(unescape(encodeURIComponent(JSON.stringify(favorites, null, 2))));
        const res = await fetch(`https://api.github.com/repos/${REPO}/contents/favorites.json`, {
          method: 'PUT',
          headers: { 'Authorization': `token ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: 'Update favorites', content, sha })
        });
        if (res.ok) {
          showToast(favorites.length ? 'Saved!' : 'Removed from saved');
        } else {
          const err = await res.json();
          showToast('Error: ' + (err.message || 'could not save'));
        }
      } catch(e) {
        showToast('Network error saving favorites');
      }
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 2500);
    }

    // Init — fetch live favorites then render
    loadFavorites();
  </script>
</body>
</html>"""

html = html.replace("UPDATED_TIME", now_str)
html = html.replace("COUNT_PLACEHOLDER", str(count))
html = html.replace("SAVED_COUNT", str(saved_count))
html = html.replace("CARDS_JSON_PLACEHOLDER", cards_json)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("index.html written successfully")
