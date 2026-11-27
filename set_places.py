"""Sætter de områder, vejret hentes for, ud fra Murats indstilling.

Brug:  python3 set_places.py '["Mørkhøj", "Aarhus", "55.74, 12.50"]'
Skriver locations.json. Første område er hovedområdet.
Stednavne slås op hos OpenStreetMap Nominatim (Danmark først, derefter hele verden).
Koordinater kan skrives som "bredde, længde", fx "55.74, 12.50".
Kendte opslag genbruges, så Nominatim kun spørges om nye navne (højst 1 opslag pr. sekund).
Exit 0 også ved fejl i enkelte navne; fejlen gemmes i locations.json.
"""
import json, re, sys, time, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timezone

OUT = "locations.json"
MAX_PLACES = 4
DEFAULT = [{"q": "Mørkhøj", "name": "Mørkhøj", "lat": 55.74, "lon": 12.50, "source": "fast standard"}]
UA = "dagens-oversigt/1.0 (+https://github.com/wghmnyg6tj-jpg/dr-rss)"
COORD = re.compile(r"^\s*(-?\d{1,2}(?:[.,]\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$")


def norm(s):
    return unicodedata.normalize("NFC", s).strip().lower()


def geocode(q):
    for extra in ({"countrycodes": "dk"}, {}):
        params = {"q": q, "format": "jsonv2", "limit": 1, "accept-language": "da", **extra}
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8"))
        time.sleep(1.1)
        if res:
            x = res[0]
            return {"lat": round(float(x["lat"]), 4), "lon": round(float(x["lon"]), 4),
                    "found": x.get("display_name", "")[:160], "source": "OpenStreetMap Nominatim"}
    return None


def main(argv):
    try:
        wanted = json.loads(argv[1]) if len(argv) > 1 and argv[1].strip() else []
    except Exception:
        wanted = []
    wanted = [str(w).strip()[:80] for w in wanted if str(w).strip()][:MAX_PLACES]
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {"places": DEFAULT}
    cache = {norm(p["q"]): p for p in prev.get("places", []) if p.get("lat") is not None}
    cache.update({norm(p["q"]): p for p in prev.get("cache", []) if p.get("lat") is not None})
    cache.setdefault(norm("Mørkhøj"), DEFAULT[0])
    if not wanted:
        wanted = ["Mørkhøj"]
    before = prev.get("requested") or [p["q"] for p in prev.get("places", [])]
    if [norm(w) for w in wanted] == [norm(x) for x in before]:
        print("Områderne er uændrede.")
        return 0
    places, errors = [], []
    for q in wanted:
        m = COORD.match(q)
        if m:
            lat, lon = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                places.append({"q": q, "name": q, "lat": round(lat, 4), "lon": round(lon, 4), "source": "koordinater"})
                continue
        c = cache.get(norm(q))
        if c:
            places.append(dict(c, q=q, name=q))
            continue
        try:
            g = geocode(q)
        except Exception as e:
            g = None
            errors.append(f"{q}: opslag fejlede ({type(e).__name__})")
        if g:
            places.append({"q": q, "name": q, **g})
        elif not any(e.startswith(q + ":") for e in errors):
            errors.append(f"{q}: stedet blev ikke fundet")
    if not places:
        places = DEFAULT
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "requested": wanted, "places": places, "errors": errors,
           "cache": list({norm(p["q"]): p for p in list(cache.values()) + places}.values())[:40]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Områder:", ", ".join(f"{p['name']} ({p['lat']}, {p['lon']})" for p in places), "| Fejl:", errors or "ingen")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
