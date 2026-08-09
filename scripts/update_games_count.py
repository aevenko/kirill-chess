"""
Auto-update games-played count in data.json (Classical / Rapid / Blitz).

ВАЖНО про методику
------------------
Источники сильно пересекаются: одна и та же партия обычно рейтингуется
одновременно FIDE, CFC и FQÉ. Предыдущая версия скрипта складывала все четыре
источника — это давало ~700 партий вместо реальных ~540.

Правильный подсчёт:

    classical = FQÉ «Lente»  n + партии турниров CFC вне Квебека (тип R)
    rapid     = FQÉ «Rapide» n + партии турниров CFC вне Квебека (тип Q)
    blitz     = FQÉ «Blitz»  n
    CMA       = отдельной строкой (школьный циркуит, без разбивки по контролю)

FQÉ — самая полная база по Квебеку и единственная, которая честно делит партии
по контролю времени. Турнир считается «вне Квебека», если CFC указывает для него
province != QC (берётся из /api/event/v1/<id>) — ручной список названий не нужен.
Внешний турнир не добавляется, если он уже посчитан в CMA (сверка по дате).

FIDE читается только для справки (в data.json["sources"]) — все партии FIDE уже
входят в базу FQÉ или в список внешних турниров CFC.

Sources:
  FIDE  https://ratings.fide.com/profile/2666243  + POST /a_data_stats.php
  CFC   https://server.chess.ca/api/player/v1/187189 + /api/event/v1/<id>
  FQÉ   https://www.fqechecs.qc.ca/membres/index.php?Id=109477
  CMA   https://chess-math.org/ratings/id/1477067
"""

import datetime
import json
import re
import sys
import urllib.parse
import urllib.request

FIDE_ID = 2666243
CFC_ID = 187189
FQE_ID = 109477
CMA_ID = 1477067

HOME_PROVINCE = "QC"

DATA_FILE = "data.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8",
}

# Зеркала CMA. chess-math.org иногда отдаёт 403 на IP дата-центров
# (в том числе раннерам GitHub Actions) — тогда пробуем французскую версию.
CMA_URLS = [
    "https://chess-math.org/ratings/id/{id}",
    "https://echecs.org/cotes/id/{id}",
]

# Запасной вариант, если CFC не отдаст карточку турнира с провинцией.
EXTERNAL_NAME_PATTERNS = [
    r"\bCYCC\b", r"\bNAYCC\b", r"\bNorth American\b", r"\bPan[- ]?Am",
    r"\bWorld (Youth|Cadet)\b", r"\bOttawa\b", r"\bToronto\b",
    r"\bNew York\b", r"\bUS Open\b",
]


def get(url, data=None, extra_headers=None):
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


# ── FQÉ — основная база ─────────────────────────────────────────────────────
def fetch_fqe():
    """Таблица профиля: Cote n | Cote n | Cote n  →  Lente / Rapide / Blitz."""
    html = get(f"https://www.fqechecs.qc.ca/membres/index.php?Id={FQE_ID}")
    text = strip_tags(html)
    m = re.search(
        r"Cote\s+n\s+Cote\s+n\s+Cote\s+n\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        text,
    )
    if not m:
        raise ValueError("FQÉ: таблица Lente/Rapide/Blitz не найдена")
    lente, lente_n, rapide, rapide_n, blitz, blitz_n = map(int, m.groups())
    return {
        "classical_rating": lente, "classical": lente_n,
        "rapid_rating": rapide, "rapid": rapide_n,
        "blitz_rating": blitz, "blitz": blitz_n,
    }


# ── CMA (Chess'n Math) — школьный циркуит ───────────────────────────────────
def fetch_cma(previous=None):
    """Читает CMA. При отказе всех зеркал возвращает снимок из data.json."""
    errors = []
    for template in CMA_URLS:
        url = template.format(id=CMA_ID)
        try:
            html = get(url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        text = strip_tags(html)

        def grab(*labels):
            for label in labels:
                m = re.search(label + r"[^0-9]{0,40}(\d+)", text, re.I)
                if m:
                    return int(m.group(1))
            return None

        total = grab("Total number of games", "Total des parties jou[ée]es")
        if total is None:
            errors.append(f"{url}: не найдено общее число партий")
            continue

        return {
            "total": total,
            "this_year": grab("Games played this year", "Parties jou[ée]es cette ann[ée]e"),
            "rating": grab("Max rating", "Cote maximale"),
            "dates": set(re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", html)),
            "stale": False,
            "url": url,
        }

    # Все зеркала недоступны — берём последний удачный снимок из data.json.
    if previous and previous.get("games_total"):
        print(
            "⚠️  CMA недоступен (" + "; ".join(errors) + ").\n"
            "    Использую последний снимок из data.json — счётчик CMA не обновится, "
            "но федерационные цифры пересчитаются корректно.",
            file=sys.stderr,
        )
        return {
            "total": previous["games_total"],
            "this_year": previous.get("games_this_year"),
            "rating": previous.get("rating"),
            "dates": set(previous.get("dates") or []),
            "stale": True,
            "url": previous.get("url", CMA_URLS[0].format(id=CMA_ID)),
        }

    raise ValueError("CMA недоступен и снимка в data.json нет: " + "; ".join(errors))


# ── CFC ─────────────────────────────────────────────────────────────────────
def fetch_cfc(cma_dates):
    data = json.loads(get(f"https://server.chess.ca/api/player/v1/{CFC_ID}"))
    player = data.get("player", {})
    events = player.get("events", [])

    regular = quick = 0
    external = []
    unknown_province = []

    for e in events:
        games = int(e.get("games_played", 0) or 0)
        rtype = e.get("rating_type", "")
        if rtype == "R":
            regular += games
        elif rtype == "Q":
            quick += games

        province = fetch_event_province(e.get("id"))
        if province:
            is_external = province != HOME_PROVINCE
        else:
            unknown_province.append(e.get("name", "?"))
            is_external = any(
                re.search(p, e.get("name", ""), re.I) for p in EXTERNAL_NAME_PATTERNS
            )

        # Уже посчитан школьным рейтингом CMA — второй раз не добавляем.
        if is_external and e.get("date_end") not in cma_dates:
            external.append({
                "name": e.get("name"),
                "date": e.get("date_end"),
                "province": province or "?",
                "type": rtype,
                "games": games,
            })

    if unknown_province:
        print(
            f"⚠️  Провинция не определена для {len(unknown_province)} турниров, "
            f"сработала проверка по названию: {'; '.join(unknown_province)}",
            file=sys.stderr,
        )

    last = events[0] if events else None
    return {
        "regular_rating": player.get("regular_rating"),
        "quick_rating": player.get("quick_rating"),
        "regular_prev": last.get("rating_pre") if last and last.get("rating_type") == "R" else None,
        "games_regular": regular,
        "games_quick": quick,
        "external": external,
        "external_classical": sum(x["games"] for x in external if x["type"] == "R"),
        "external_rapid": sum(x["games"] for x in external if x["type"] == "Q"),
        "updated": data.get("updated"),
    }


def fetch_event_province(event_id):
    if not event_id:
        return None
    try:
        raw = get(f"https://server.chess.ca/api/event/v1/{event_id}")
        return json.loads(raw).get("event", {}).get("province")
    except Exception:
        return None


# ── FIDE — только для справки ───────────────────────────────────────────────
def fetch_fide():
    html = get(f"https://ratings.fide.com/profile/{FIDE_ID}")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    progress = []
    for row in rows:
        cells = [strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if cells and re.fullmatch(r"\d{4}-[A-Za-z]{3}", cells[0]):
            progress.append(cells)
    if not progress:
        raise ValueError("FIDE: таблица Progress не найдена")

    def cell(row, i):
        m = re.search(r"-?\d+", row[i]) if i < len(row) else None
        return int(m.group()) if m else None

    body = urllib.parse.urlencode({"id1": FIDE_ID, "id2": 0}).encode()
    stats = json.loads(get(
        f"https://ratings.fide.com/a_data_stats.php?id1={FIDE_ID}&id2=0",
        data=body,
        extra_headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://ratings.fide.com/profile/{FIDE_ID}/statistics",
        },
    ))
    s = stats[0] if isinstance(stats, list) else stats

    def total(a, b):
        return int(s.get(a, 0) or 0) + int(s.get(b, 0) or 0)

    return {
        "period": progress[0][0],
        "standard": cell(progress[0], 1),
        "standard_prev": cell(progress[1], 1) if len(progress) > 1 else None,
        "rapid": cell(progress[0], 3),
        "blitz": cell(progress[0], 5),
        "games": {
            "total": total("white_total", "black_total"),
            "standard": total("white_total_std", "black_total_std"),
            "rapid": total("white_total_rpd", "black_total_rpd"),
            "blitz": total("white_total_blz", "black_total_blz"),
        },
    }


# ── Run ─────────────────────────────────────────────────────────────────────
def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        D = json.load(f)

    cma = fetch_cma(previous=(D.get("sources") or {}).get("cma"))
    mark = " (снимок из data.json)" if cma["stale"] else ""
    print(f"✅ CMA : {cma['total']} партий, {len(cma['dates'])} турниров, "
          f"рейтинг {cma['rating']}{mark}")

    fqe = fetch_fqe()
    print(f"✅ FQÉ : lente {fqe['classical_rating']}/{fqe['classical']}  "
          f"rapide {fqe['rapid_rating']}/{fqe['rapid']}  "
          f"blitz {fqe['blitz_rating']}/{fqe['blitz']}")

    cfc = fetch_cfc(cma["dates"])
    print(f"✅ CFC : regular {cfc['regular_rating']}, quick {cfc['quick_rating']}, "
          f"партий {cfc['games_regular']} R / {cfc['games_quick']} Q")

    try:
        fide = fetch_fide()
        print(f"✅ FIDE: {fide['standard']} ({fide['period']}), партий "
              f"{fide['games']['standard']} кл / {fide['games']['rapid']} рап / "
              f"{fide['games']['blitz']} блиц")
    except Exception as e:
        print(f"⚠️  FIDE fetch failed: {e}", file=sys.stderr)
        fide = None

    if cfc["external"]:
        print("   Турниры вне Квебека, добавленные к базе FQÉ:")
        for e in cfc["external"]:
            print(f"     · {e['date']}  [{e['province']}]  {e['name']} — "
                  f"{e['games']} партий ({e['type']})")
    else:
        print("   Внешних турниров сверх FQÉ не найдено.")

    classical = fqe["classical"] + cfc["external_classical"]
    rapid = fqe["rapid"] + cfc["external_rapid"]
    blitz = fqe["blitz"]
    federation = classical + rapid + blitz
    total = federation + cma["total"]

    print("─" * 60)
    print(f"   ИТОГО: классика {classical}, рапид {rapid}, блиц {blitz} "
          f"= {federation} федерационных + {cma['total']} школьных = {total}")

    today = datetime.date.today().isoformat()
    about = D.setdefault("about", {})
    before = json.dumps(about, sort_keys=True, ensure_ascii=False)

    about.update({
        "games_classical": classical,
        "games_rapid": rapid,
        "games_blitz": blitz,
        "games_federation": federation,
        "games_scholastic_cma": cma["total"],
        "games_recorded": total,
        "games_updated": today,
        "games_sources_note": (
            f"FQÉ (lente {fqe['classical']} / rapide {fqe['rapid']} / blitz {fqe['blitz']})"
            f" + внешние турниры CFC ({cfc['external_classical']} классика,"
            f" {cfc['external_rapid']} рапид)"
            f" + школьный циркуит CMA ({cma['total']}). Сверено {today}."
        ),
    })

    D["sources"] = {
        "checked_at": today,
        "fide": None if not fide else {
            "url": f"https://ratings.fide.com/profile/{FIDE_ID}",
            "period": fide["period"],
            "standard": fide["standard"],
            "games": fide["games"],
        },
        "cfc": {
            "url": f"https://www.chess.ca/en/ratings/p/?id={CFC_ID}",
            "updated": cfc["updated"],
            "regular": cfc["regular_rating"],
            "quick": cfc["quick_rating"],
            "games_regular": cfc["games_regular"],
            "games_quick": cfc["games_quick"],
            "external_events": cfc["external"],
        },
        "fqe": {
            "url": f"https://www.fqechecs.qc.ca/membres/index.php?Id={FQE_ID}",
            "classical": [fqe["classical_rating"], fqe["classical"]],
            "rapid": [fqe["rapid_rating"], fqe["rapid"]],
            "blitz": [fqe["blitz_rating"], fqe["blitz"]],
        },
        "cma": {
            "url": cma["url"],
            "rating": cma["rating"],
            "games_total": cma["total"],
            "games_this_year": cma["this_year"],
            "tournaments": len(cma["dates"]),
            "stale": cma["stale"],
            # Даты нужны, чтобы не посчитать турнир дважды, если CMA
            # окажется недоступен при следующем запуске.
            "dates": sorted(cma["dates"]),
        },
    }

    if json.dumps(about, sort_keys=True, ensure_ascii=False) != before:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("💾 data.json saved.")
    else:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("ℹ️  Счётчики партий не изменились (обновлён только блок sources).")


if __name__ == "__main__":
    main()
