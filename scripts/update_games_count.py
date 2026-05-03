"""
Auto-update games-played count in data.json (Classical / Rapid / Blitz).
Runs weekly via GitHub Actions.

Sources & mapping:
  FIDE       https://ratings.fide.com/profile/2666243
             period table → STD GMS (Classical), RPD GMS (Rapid), BLZ GMS (Blitz)
  CFC        https://server.chess.ca/api/player/v1/187189
             events[].games_played by rating_type:
               R = Regular  → Classical
               Q = Quick    → Rapid  (CFC tracks rapid+blitz together as "Quick")
  FQÉ        https://www.fqechecs.qc.ca/membres/index.php?Id=109477
             profile table → Lente (Classical), Rapide (Rapid), Blitz (Blitz)
  CAM        https://echecs.org/cotes/id/1477067
             "Total des parties jouées : N" → all Rapid
"""

import json, re, sys
import urllib.request

FIDE_ID       = 2666243
CFC_ID        = 187189
FQE_ID        = 109477
CAM_ID        = 1477067

DATA_FILE = "data.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KirillChessBot/1.0)"}


def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


# ── FIDE ────────────────────────────────────────────────────────────────────
def fetch_fide_games(fide_id):
    """Sum STD GMS / RPD GMS / BLZ GMS from FIDE period table."""
    html = get(f"https://ratings.fide.com/profile/{fide_id}")
    m = re.search(
        r'<table[^>]*class="profile-table_calc"[^>]*>(.*?)</table>',
        html, re.S
    )
    if not m:
        raise ValueError("FIDE period table not found")
    rows = re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S)
    std = rpd = blz = 0
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) == 7:                       # Period, STD, STD-GMS, RPD, RPD-GMS, BLZ, BLZ-GMS
            def num(s):
                s = re.sub(r"<[^>]+>|&nbsp;|\s", "", s)
                return int(s) if s.isdigit() else 0
            std += num(cells[2])
            rpd += num(cells[4])
            blz += num(cells[6])
    return {"classical": std, "rapid": rpd, "blitz": blz}


# ── CFC ─────────────────────────────────────────────────────────────────────
def fetch_cfc_games(cfc_id):
    """Sum games_played per rating_type. R → Classical, Q → Rapid."""
    data = json.loads(get(f"https://server.chess.ca/api/player/v1/{cfc_id}"))
    events = data.get("player", {}).get("events", [])
    out = {"classical": 0, "rapid": 0, "blitz": 0}
    for e in events:
        gms = int(e.get("games_played", 0) or 0)
        t   = e.get("rating_type", "")
        if t == "R":
            out["classical"] += gms
        elif t == "Q":
            out["rapid"] += gms                   # CFC "Quick" → bucket as Rapid
    return out


# ── FQÉ ─────────────────────────────────────────────────────────────────────
def fetch_fqe_games(fqe_id):
    """Parse Lente / Rapide / Blitz games from member profile table."""
    html = get(f"https://www.fqechecs.qc.ca/membres/index.php?Id={fqe_id}")
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = re.search(
        r"Cote\s+n\s+Cote\s+n\s+Cote\s+n\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        text
    )
    if not m:
        raise ValueError("FQÉ profile table not found")
    _, lente_n, _, rapide_n, _, blitz_n = map(int, m.groups())
    return {"classical": lente_n, "rapid": rapide_n, "blitz": blitz_n}


# ── CAM (echecs.org) ────────────────────────────────────────────────────────
def fetch_cam_games(cam_id):
    """All CAM games are Rapid. Parse 'Total des parties jouées : N'."""
    html = get(f"https://echecs.org/cotes/id/{cam_id}")
    text = re.sub(r"<[^>]+>", " ", html)
    m = re.search(r"Total des parties jou[ée]es\s*:\s*(\d+)", text)
    if not m:
        raise ValueError("CAM total games not found")
    return {"classical": 0, "rapid": int(m.group(1)), "blitz": 0}


# ── Run ─────────────────────────────────────────────────────────────────────
def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        D = json.load(f)

    sources = [
        ("FIDE", fetch_fide_games, FIDE_ID),
        ("CFC",  fetch_cfc_games,  CFC_ID),
        ("FQÉ",  fetch_fqe_games,  FQE_ID),
        ("CAM",  fetch_cam_games,  CAM_ID),
    ]

    totals = {"classical": 0, "rapid": 0, "blitz": 0}
    breakdown = {}

    for label, fn, arg in sources:
        try:
            res = fn(arg)
            breakdown[label] = res
            for k in totals:
                totals[k] += res[k]
            print(f"✅ {label}: classical={res['classical']:>3}  rapid={res['rapid']:>3}  blitz={res['blitz']:>3}")
        except Exception as e:
            print(f"⚠️  {label} fetch failed: {e}", file=sys.stderr)

    grand_total = sum(totals.values())
    print("─" * 50)
    print(f"   TOTAL classical={totals['classical']}  rapid={totals['rapid']}  blitz={totals['blitz']}  ⇒ {grand_total}")

    about = D.setdefault("about", {})
    changed = False

    for k_short, k_full in [("classical", "games_classical"),
                            ("rapid",     "games_rapid"),
                            ("blitz",     "games_blitz")]:
        if about.get(k_full) != totals[k_short]:
            about[k_full] = totals[k_short]
            changed = True

    if about.get("games_recorded") != grand_total:
        about["games_recorded"] = grand_total
        changed = True

    if changed:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False, indent=2)
        print("💾 data.json saved.")
    else:
        print("ℹ️  No changes — data.json unchanged.")


if __name__ == "__main__":
    main()
