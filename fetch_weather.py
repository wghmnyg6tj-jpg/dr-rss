"""Henter vejrdata til Dagens oversigt og gemmer dem i weather.json.

Kilder (alle gratis, ingen nøgle):
- DMI HARMONIE DINI (prognose, ca. 2 km), opendataapi.dmi.dk, nærmeste gitterpunkt til Mørkhøj
- DMI målinger (metObs): Jægersborg 06181 (ca. 3 km), Kastrup 06180, Landbohøjskolen 06186
- DMI lyn (lightningdata) i et område omkring København
- met.no locationforecast compact (prognose med vejrsymboler)

Hver kilde hentes for sig. Fejler en kilde, beholdes de forrige data for den kilde,
og fejlen skrives i "status". Tal gemmes uden afrunding ud over 2 decimaler.
"""
import json, sys, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

LAT, LON = 55.74, 12.50  # Mørkhøj
STATIONS = [("06181", "Jægersborg"), ("06180", "Kastrup"), ("06186", "Landbohøjskolen")]
OBS_PARAMS = ["temp_dry", "wind_speed", "wind_dir", "wind_max", "humidity",
              "precip_past10min", "precip_past1h", "visibility", "weather", "cloud_cover", "temp_grass"]
LIGHTNING_BBOX = "11.9,55.4,13.1,56.1"
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


def get_json(url, headers=None, timeout=20):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), json.loads(r.read().decode("utf-8"))


def r2(x):
    return None if x is None else round(float(x), 2)


def dmi_forecast(now):
    status, _, inst = get_json(f"{DMI}/v1/forecastedr/collections/harmonie_dini_sf/instances")
    ids = sorted(i["id"] for i in inst.get("instances", []))
    run = ids[-1] if ids else None
    start = now.replace(minute=0, second=0) - timedelta(hours=1)
    end = start + timedelta(hours=38)
    url = (f"{DMI}/v1/forecastedr/collections/harmonie_dini_sf/position"
           f"?coords=POINT%28{LON}%20{LAT}%29&crs=crs84&parameter-name={','.join(DMI_PARAMS)}&f=GeoJSON"
           f"&datetime={start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}/{end.strftime('%Y-%m-%dT%H:%M:%S.000Z')}")
    _, _, j = get_json(url, timeout=30)
    feats = j.get("features", [])
    if not feats:
        raise ValueError("ingen data fra DMI-prognosen")
    rows = []
    for f in feats:
        p = f["properties"]
        rows.append({"t": p["step"].replace(".000Z", "Z"), "p": p})
    rows.sort(key=lambda r: r["t"])
    hours = {}
    for i, r in enumerate(rows):
        p = r["p"]
        nxt = rows[i + 1]["p"] if i + 1 < len(rows) else None
        mm = None
        ptype = None
        if nxt is not None and p.get("total-precipitation") is not None and nxt.get("total-precipitation") is not None:
            mm = max(0.0, float(nxt["total-precipitation"]) - float(p["total-precipitation"]))
            mm = round(mm, 2)
            pt = nxt.get("precipitation-type")
            if mm >= 0.05 and pt is not None:
                ptype = PTYPE.get(int(pt), f"kode {pt}")
        t2 = p.get("temperature-2m")
        t0 = p.get("temperature-0m")
        hours[r["t"]] = {
            "t2": r2(t2 - 273.15) if t2 is not None else None,
            "t0": r2(t0 - 273.15) if t0 is not None else None,
            "ws": r2(p.get("wind-speed-10m")),
            "wd": r2(p.get("wind-dir-10m")),
            "gust": r2(p.get("gust-wind-speed-10m")),
            "mm": mm,              # nedbør i timen, der starter på t
            "ptype": ptype,        # nedbørstype i den time (kun når mm >= 0,05)
            "cloud": r2(p.get("fraction-of-cloud-cover")),
            "vis": r2(p.get("visibility")),
        }
    coords = feats[0].get("geometry", {}).get("coordinates")
    return {"run": run, "point": coords, "hours": hours}


def metno(prev):
    headers = {}
    if prev and prev.get("last_modified"):
        headers["If-Modified-Since"] = prev["last_modified"]
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"
    try:
        status, h, j = get_json(url, headers=headers)
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
            continue  # kun timer med 1-timesprognose
        inst = d["instant"]["details"]
        hours[ts["time"]] = {
            "t2": inst.get("air_temperature"),
            "ws": inst.get("wind_speed"),
            "wd": inst.get("wind_from_direction"),
            "sym": n1["summary"]["symbol_code"],
            "mm": n1.get("details", {}).get("precipitation_amount"),
        }
    return {"updated_at": props["meta"]["updated_at"], "last_modified": h.get("Last-Modified"),
            "point": j.get("geometry", {}).get("coordinates"), "hours": hours}


def observations():
    out = {}
    for sid, name in STATIONS:
        _, _, j = get_json(f"{DMI}/v2/metObs/collections/observation/items?stationId={sid}&period=latest-hour&limit=1000")
        latest = {}
        for f in j.get("features", []):
            p = f["properties"]
            k = p["parameterId"]
            if k not in OBS_PARAMS:
                continue
            if k not in latest or p["observed"] > latest[k]["observed"]:
                latest[k] = {"value": p["value"], "observed": p["observed"]}
        coords = j["features"][0]["geometry"]["coordinates"] if j.get("features") else None
        out[sid] = {"name": name, "point": coords, "values": latest}
    return out


def lightning():
    res = {}
    for period in ("latest-hour", "latest-day"):
        _, _, j = get_json(f"{DMI}/v2/lightningdata/collections/observation/items?bbox={LIGHTNING_BBOX}&period={period}&limit=10000")
        res[period] = j.get("numberReturned", len(j.get("features", [])))
    return {"bbox": LIGHTNING_BBOX, "count_last_hour": res["latest-hour"], "count_last_day": res["latest-day"]}


def main():
    now = now_utc()
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {}
    out = {"generated": iso(now), "location": {"name": "Mørkhøj", "lat": LAT, "lon": LON}, "status": {}}
    jobs = [("dmi_forecast", lambda: dmi_forecast(now)),
            ("metno", lambda: metno(prev.get("metno"))),
            ("observations", observations),
            ("lightning", lightning)]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {key: pool.submit(fn) for key, fn in jobs}
    for key, fn in jobs:
        try:
            data = futs[key].result()
            data["fetched"] = iso(now) if not (isinstance(data, dict) and data.get("not_modified")) else prev.get(key, {}).get("fetched", iso(now))
            data.pop("not_modified", None)
            out[key] = data
            out["status"][key] = "ok"
        except Exception as e:
            msg = f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else f"fejl: {type(e).__name__}: {e}"[:200]
            out["status"][key] = msg
            if key in prev:
                out[key] = prev[key]  # behold forrige data; "fetched" viser deres alder
        print(f"{key}: {out['status'][key]}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
