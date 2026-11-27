"""Henter vejrdata til Dagens oversigt og gemmer dem i weather.json.

Områderne står i locations.json (første = hovedområde). Mangler filen, bruges Mørkhøj.
Pr. område:
- DMI HARMONIE DINI (prognose, ca. 2 km), nærmeste gitterpunkt (kun inden for DMI's modelområde)
- met.no locationforecast compact (prognose med vejrsymboler, hele verden)
- de 4 nærmeste aktive DMI-stationer, der måler temperatur (metObs), med seneste værdier
For hovedområdet desuden: DMI-lyn i et område omkring stedet.
Hver kilde hentes for sig. Fejler en kilde, beholdes de forrige data for den kilde,
og fejlen skrives i "status". Alle kald har gentagelse ved HTTP 429/5xx.
"""
import json, os, socket, math, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

DEFAULT_PLACES = [{"q": "Mørkhøj", "name": "Mørkhøj", "lat": 55.74, "lon": 12.50}]
OBS_PARAMS = ["temp_dry", "wind_speed", "wind_dir", "wind_max", "humidity",
              "precip_past10min", "precip_past1h", "visibility", "weather", "cloud_cover", "temp_grass"]
DMI = "https://opendataapi.dmi.dk"
DMI_PARAMS = ["temperature-2m", "temperature-0m", "wind-speed-10m", "wind-dir-10m", "gust-wind-speed-10m",
              "total-precipitation", "precipitation-type", "fraction-of-cloud-cover", "visibility"]
# DMI's kodetabel for precipitation-type
PTYPE = {0: "støvregn", 1: "regn", 2: "slud", 3: "sne", 4: "frysende støvregn", 5: "isslag", 6: "kornsne", 7: "hagl"}
UA = "dagens-oversigt/1.0 (+https://github.com/wghmnyg6tj-jpg/dr-rss)"
OUT = "weather.json"


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(url, headers=None, timeout=20, tries=4, timeout_retry=True):
    """Henter JSON. Ved HTTP 429/502/503/504 ventes (Retry-After eller 2, 4, 8 s), og der prøves igen.
    Ved timeout prøves én gang til (DMI svarer af og til ikke)."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    timeouts = 0
    n = 0
    while True:
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            n += 1
            if e.code in (429, 502, 503, 504) and n < tries:
                ra = e.headers.get("Retry-After") if e.headers else None
                wait = float(ra) if ra and ra.replace(".", "", 1).isdigit() else 2 ** n
                time.sleep(min(wait, 20))
                continue
            raise
        except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
            is_to = isinstance(e, (TimeoutError, socket.timeout)) or isinstance(getattr(e, "reason", None), (TimeoutError, socket.timeout))
            if is_to and timeout_retry and timeouts < 1:
                timeouts += 1
                time.sleep(1)
                continue
            raise


def r2(x):
    return None if x is None else round(float(x), 2)


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


_run_cache = {}


def dmi_run():
    if "run" not in _run_cache:
        _, _, inst = get_json(f"{DMI}/v1/forecastedr/collections/harmonie_dini_sf/instances")
        ids = sorted(i["id"] for i in inst.get("instances", []))
        _run_cache["run"] = ids[-1] if ids else None
    return _run_cache["run"]


def dmi_forecast(lat, lon, now, primary=True):
    run = dmi_run()
    start = now.replace(minute=0, second=0) - timedelta(hours=1)
    end = start + timedelta(hours=38)
    url = (f"{DMI}/v1/forecastedr/collections/harmonie_dini_sf/position"
           f"?coords=POINT%28{round(lon, 4)}%20{round(lat, 4)}%29&crs=crs84&parameter-name={','.join(DMI_PARAMS)}&f=GeoJSON"
           f"&datetime={start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}/{end.strftime('%Y-%m-%dT%H:%M:%S.000Z')}")
    _, _, j = get_json(url, timeout=12 if primary else 10, timeout_retry=primary)
    feats = j.get("features", [])
    if not feats:
        raise ValueError("ingen data fra DMI-prognosen (stedet ligger måske uden for DMI's modelområde)")
    rows = sorted(({"t": f["properties"]["step"].replace(".000Z", "Z"), "p": f["properties"]} for f in feats), key=lambda r: r["t"])
    hours = {}
    for i, r in enumerate(rows):
        p = r["p"]
        nxt = rows[i + 1]["p"] if i + 1 < len(rows) else None
        mm, ptype = None, None
        if nxt is not None and p.get("total-precipitation") is not None and nxt.get("total-precipitation") is not None:
            mm = round(max(0.0, float(nxt["total-precipitation"]) - float(p["total-precipitation"])), 2)
            pt = nxt.get("precipitation-type")
            if mm >= 0.05 and pt is not None:
                ptype = PTYPE.get(int(pt), f"kode {pt}")
        t2, t0 = p.get("temperature-2m"), p.get("temperature-0m")
        hours[r["t"]] = {
            "t2": r2(t2 - 273.15) if t2 is not None else None,
            "t0": r2(t0 - 273.15) if t0 is not None else None,
            "ws": r2(p.get("wind-speed-10m")), "wd": r2(p.get("wind-dir-10m")),
            "gust": r2(p.get("gust-wind-speed-10m")),
            "mm": mm,          # nedbør i timen, der starter på t
            "ptype": ptype,    # nedbørstype i den time (kun når mm >= 0,05)
            "cloud": r2(p.get("fraction-of-cloud-cover")), "vis": r2(p.get("visibility")),
        }
    coords = feats[0].get("geometry", {}).get("coordinates")
    if coords and km(lat, lon, coords[1], coords[0]) > 15:
        raise ValueError(f"DMI's nærmeste gitterpunkt ligger {round(km(lat, lon, coords[1], coords[0]))} km væk (uden for modelområdet)")
    return {"run": run, "point": coords, "hours": hours}


def metno(lat, lon, prev):
    headers = {}
    if prev and prev.get("last_modified") and prev.get("lat") == lat and prev.get("lon") == lon:
        headers["If-Modified-Since"] = prev["last_modified"]
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        _, h, j = get_json(url, headers=headers)
    except urllib.error.HTTPError as e:
        if e.code == 304 and prev:
            return dict(prev, not_modified=True)
        raise
    props = j["properties"]
    hours = {}
    for ts in props["timeseries"]:
        d = ts["data"]
        n1 = d.get("next_1_hours")
        if not n1:
            continue
        inst = d["instant"]["details"]
        hours[ts["time"]] = {"t2": inst.get("air_temperature"), "ws": inst.get("wind_speed"),
                             "wd": inst.get("wind_from_direction"), "sym": n1["summary"]["symbol_code"],
                             "mm": n1.get("details", {}).get("precipitation_amount")}
    return {"updated_at": props["meta"]["updated_at"], "last_modified": h.get("Last-Modified"),
            "lat": lat, "lon": lon, "point": j.get("geometry", {}).get("coordinates"), "hours": hours}


def observations(lat, lon):
    """De 4 nærmeste aktive DMI-stationer med temperatur, med seneste værdier (nogle sender ikke hvert 10. minut)."""
    _, _, j = get_json(f"{DMI}/v2/metObs/collections/station/items?bbox={round(lon - 0.9, 3)},{round(lat - 0.5, 3)},{round(lon + 0.9, 3)},{round(lat + 0.5, 3)}&status=Active&limit=500")
    cands = {}
    for f in j.get("features", []):
        p = f["properties"]
        if "temp_dry" not in (p.get("parameterId") or []):
            continue
        c = f["geometry"]["coordinates"]
        sid = p["stationId"]
        d = km(lat, lon, c[1], c[0])
        if sid not in cands or d < cands[sid]["dist_km"]:
            cands[sid] = {"name": p.get("name", sid), "point": c, "dist_km": round(d, 1)}
    near = sorted(cands.items(), key=lambda kv: kv[1]["dist_km"])[:4]
    out = {}
    for sid, info in near:
        _, _, o = get_json(f"{DMI}/v2/metObs/collections/observation/items?stationId={sid}&period=latest-hour&limit=1000")
        latest = {}
        for f in o.get("features", []):
            p = f["properties"]
            k = p["parameterId"]
            if k in OBS_PARAMS and (k not in latest or p["observed"] > latest[k]["observed"]):
                latest[k] = {"value": p["value"], "observed": p["observed"]}
        out[sid] = dict(info, values=latest)
    return out


def lightning(lat, lon):
    bbox = f"{round(lon - 0.6, 2)},{round(lat - 0.35, 2)},{round(lon + 0.6, 2)},{round(lat + 0.35, 2)}"
    res = {}
    for period in ("latest-hour", "latest-day"):
        _, _, j = get_json(f"{DMI}/v2/lightningdata/collections/observation/items?bbox={bbox}&period={period}&limit=10000")
        res[period] = j.get("numberReturned", len(j.get("features", [])))
    return {"bbox": bbox, "count_last_hour": res["latest-hour"], "count_last_day": res["latest-day"]}


def load_places():
    try:
        L = json.load(open("locations.json", encoding="utf-8"))
        pl = [p for p in L.get("places", []) if p.get("lat") is not None]
        return pl or DEFAULT_PLACES, L.get("errors", [])
    except Exception:
        return DEFAULT_PLACES, []


def err(e):
    return (f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else f"fejl: {e}")[:200]


def place_job(pl, old, now, primary=True):
    lat, lon = float(pl["lat"]), float(pl["lon"])
    res = {"name": pl.get("name"), "q": pl.get("q"), "lat": lat, "lon": lon, "found": pl.get("found"), "status": {}}
    with ThreadPoolExecutor(max_workers=1) as pool:
        fm = pool.submit(metno, lat, lon, old.get("metno"))  # met.no samtidig med DMI
        for key, fn in (("dmi_forecast", lambda: dmi_forecast(lat, lon, now, primary)),
                        ("observations", lambda: {"stations": observations(lat, lon)})):
            try:
                res[key] = {"fetched": iso(now), **fn()}
                res["status"][key] = "ok"
            except Exception as e:
                res["status"][key] = err(e)
                if key in old:
                    res[key] = old[key]
        try:
            m = fm.result()
            nm = m.pop("not_modified", False)
            m["fetched"] = old.get("metno", {}).get("fetched", iso(now)) if nm else iso(now)
            res["metno"] = m
            res["status"]["metno"] = "ok"
        except Exception as e:
            res["status"]["metno"] = err(e)
            if "metno" in old:
                res["metno"] = old["metno"]
    return res


def main():
    now = now_utc()
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {}
    prev_places = {(p.get("name"), p.get("lat"), p.get("lon")): p for p in prev.get("places", [])}
    places, loc_errors = load_places()
    out = {"version": 2, "generated": iso(now), "status": {}, "places": [], "location_errors": loc_errors}
    for i, pl in enumerate(places):
        old = prev_places.get((pl.get("name"), float(pl["lat"]), float(pl["lon"])), {})
        r = place_job(pl, old, now, primary=(i == 0))
        out["places"].append(r)
        print(f"{r['name']}: {r['status']}")
    p0 = out["places"][0]
    try:
        out["lightning"] = {"fetched": iso(now), **lightning(p0["lat"], p0["lon"])}
        out["status"]["lightning"] = "ok"
    except Exception as e:
        out["status"]["lightning"] = err(e)
        if "lightning" in prev:
            out["lightning"] = prev["lightning"]
    out["status"].update(p0["status"])
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)      # atomisk: build_page.py/vejr_html.py læser aldrig en halv fil
    return 0


if __name__ == "__main__":
    sys.exit(main())
