"""
Auto-update chess ratings in data.json.
Sources:
  FIDE       – https://ratings.fide.com/profile/2666243
  CFC        – https://server.chess.ca/api/player/v1/187189  (official JSON API)
  FQÉ        – https://www.fqechecs.qc.ca/membres/json-cote.php?id=109477&c=1
  Chess.com  – https://api.chess.com/pub/player/future_grandmaster14/stats  (Rapid)
"""

import json, re, sys
import urllib.request

FIDE_ID       = 2666243
CFC_ID        = 187189
FQE_ID        = 109477
CHESSCOM_USER = "future_grandmaster14"

DATA_FILE = "data.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KirillChessBot/1.0)"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_fide(fide_id):
    html = get(f"https://ratings.fide.com/profile/{fide_id}")
    # Try multiple patterns in case FIDE changes their HTML
    patterns = [
        r"<p>(\d{3,4})</p><p[^>]*>STANDARD",          # original
        r'"std_rtng"\s*:\s*"?(\d{3,4})"?',             # JSON-in-HTML
        r'STANDARD[^<]*</[^>]+>\s*<[^>]+>\s*(\d{3,4})',# reversed order
        r'(\d{3,4})</p>\s*<p[^>]*>\s*STANDARD',        # slight variant
        r'class="profile-top-rating-data"[^>]*>\s*(\d{3,4})',  # new layout
    ]
    for pat in patterns:
        m = re.search(pat, html, re.S)
        if m:
            return int(m.group(1))
    raise ValueError("FIDE standard rating not found — page structure may have changed")


def fetch_cfc(cfc_id):
    data = json.loads(get(f"https://server.chess.ca/api/player/v1/{cfc_id}"))
    player = data.get("player", {})
    rating = player.get("regular_rating") or player.get("regular_rating_calc")
    if rating is None:
        raise ValueError("CFC regular_rating not found in API response")
    return int(rating)


def fetch_fqe(fqe_id):
    history = json.loads(get(
        f"https://www.fqechecs.qc.ca/membres/json-cote.php?id={fqe_id}&c=1"
    ))
    if not history:
        raise ValueError("FQÉ history is empty")
    return int(history[-1]["Cote"])


def fetch_chesscom(username):
    data = json.loads(get(
        f"https://api.chess.com/pub/player/{username}/stats"
    ))
    rapid = data.get("chess_rapid", {})
    rating = rapid.get("last", {}).get("rating")
    if rating is None:
        raise ValueError("Chess.com Rapid rating not found")
    return int(rating)


def fmt_delta(diff):
    return f"+{diff}" if diff > 0 else str(diff)


# ── Load data.json ───────────────────────────────────────────────────────────
with open(DATA_FILE, encoding="utf-8") as f:
    D = json.load(f)

# ── Fetch ────────────────────────────────────────────────────────────────────
new_values = {}
failures   = []

for label, fn, args in [
    ("FIDE",      fetch_fide,     (FIDE_ID,)),
    ("CFC",       fetch_cfc,      (CFC_ID,)),
    ("FQÉ",       fetch_fqe,      (FQE_ID,)),
    ("Chess.com", fetch_chesscom, (CHESSCOM_USER,)),
]:
    try:
        val = fn(*args)
        new_values[label] = val
        print(f"✅ {label}: {val}")
    except Exception as e:
        failures.append(label)
        print(f"⚠️  {label} fetch failed: {e}", file=sys.stderr)

# Fail loudly if ALL sources failed (likely a network or structural issue)
if not new_values:
    print("❌ All sources failed — aborting without changes.", file=sys.stderr)
    sys.exit(1)

# ── Update ratings array ─────────────────────────────────────────────────────
changed = False
for r in D.get("ratings", []):
    for key, new_val in new_values.items():
        if r["org"].startswith(key):
            old_val = r.get("value", 0)
            if old_val != new_val:
                diff        = new_val - old_val
                r["value"]     = new_val
                r["delta"]     = fmt_delta(diff)
                r["direction"] = "up" if diff > 0 else "down"
                print(f"   {r['org']}: {old_val} → {new_val}  ({r['delta']})")
                changed = True
            break

# ── Update hero_stats ─────────────────────────────────────────────────────────
hs = D.setdefault("hero_stats", {})
if "FIDE" in new_values:
    old = hs.get("fide_rating", 0)
    hs["fide_rating"] = new_values["FIDE"]
    if old != new_values["FIDE"]:
        hs["fide_delta"] = fmt_delta(new_values["FIDE"] - old)
        changed = True
if "CFC" in new_values:
    hs["cfc_rating"] = new_values["CFC"]

# ── Save ──────────────────────────────────────────────────────────────────────
if changed:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=2)
    print("💾 data.json saved.")
else:
    print("ℹ️  No rating changes — data.json unchanged.")

if failures:
    print(f"⚠️  Partial failure — could not fetch: {', '.join(failures)}", file=sys.stderr)
