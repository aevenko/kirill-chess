"""
Auto-update chess ratings in data.json.
Sources:
  FIDE  – https://ratings.fide.com/profile/2666243
  CFC   – https://server.chess.ca/api/player/v1/187189  (official JSON API)
  FQÉ   – https://www.fqechecs.qc.ca/membres/json-cote.php?id=109477&c=1
"""

import json, re, sys
import urllib.request

FIDE_ID = 2666243
CFC_ID  = 187189
FQE_ID  = 109477

DATA_FILE = "data.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KirillChessBot/1.0)"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")


def fetch_fide(fide_id):
    html = get(f"https://ratings.fide.com/profile/{fide_id}")
    # <p>1721</p><p style="...">STANDARD …</p>
    m = re.search(r"<p>(\d{3,4})</p><p[^>]*>STANDARD", html)
    if m:
        return int(m.group(1))
    raise ValueError("FIDE rating not found in page")


def fetch_cfc(cfc_id):
    data = json.loads(get(f"https://server.chess.ca/api/player/v1/{cfc_id}"))
    return int(data["player"]["regular_rating"])


def fetch_fqe(fqe_id):
    # Returns array of {"Quand": "...", "Cote": 1782} — last entry is current
    history = json.loads(get(
        f"https://www.fqechecs.qc.ca/membres/json-cote.php?id={fqe_id}&c=1"
    ))
    if not history:
        raise ValueError("FQÉ history is empty")
    return int(history[-1]["Cote"])


def fmt_delta(diff):
    return f"+{diff}" if diff > 0 else str(diff)


# ── Load data.json ──────────────────────────────────────────────────────────
with open(DATA_FILE, encoding="utf-8") as f:
    D = json.load(f)

# ── Fetch ───────────────────────────────────────────────────────────────────
new_values = {}

for label, fn, args in [
    ("FIDE",          fetch_fide, (FIDE_ID,)),
    ("CFC",           fetch_cfc,  (CFC_ID,)),
    ("FQÉ",           fetch_fqe,  (FQE_ID,)),
]:
    try:
        val = fn(*args)
        new_values[label] = val
        print(f"✅ {label}: {val}")
    except Exception as e:
        print(f"⚠️  {label} fetch failed: {e}", file=sys.stderr)

# ── Update ratings array ─────────────────────────────────────────────────────
# Match by prefix so "CFC (Chess Canada)" matches key "CFC", "FQÉ (Québec)" → "FQÉ"
changed = False
for r in D.get("ratings", []):
    for key, new_val in new_values.items():
        if r["org"].startswith(key):
            old_val = r.get("value", 0)
            if old_val != new_val:
                diff = new_val - old_val
                r["value"]     = new_val
                r["delta"]     = fmt_delta(diff)
                r["direction"] = "up" if diff > 0 else "down"
                print(f"   {r['org']}: {old_val} → {new_val}  ({r['delta']})")
                changed = True
            break

# ── Update hero_stats ────────────────────────────────────────────────────────
hs = D.setdefault("hero_stats", {})
if "FIDE" in new_values:
    old = hs.get("fide_rating", 0)
    hs["fide_rating"] = new_values["FIDE"]
    if old != new_values["FIDE"]:
        hs["fide_delta"] = fmt_delta(new_values["FIDE"] - old)
        changed = True
if "CFC" in new_values:
    hs["cfc_rating"] = new_values["CFC"]

# ── Save ─────────────────────────────────────────────────────────────────────
if changed:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=2)
    print("💾 data.json saved.")
else:
    print("ℹ️  No rating changes — data.json unchanged.")
