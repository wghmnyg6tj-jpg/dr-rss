"""Laver et radarbillede (radar.png + radar.json) omkring hovedområdet ud fra DMI's radarkomposit.

Kilde: DMI Open Data, radardata/composite (HDF5, ODIM). Ingen nøgle.
Billedet: 200 x 200 km omkring hovedområdet, kystlinjer (Natural Earth), rød prik = stedet.
Farver efter radarens styrke (dBZ). Omregning til mm/t med Marshall-Palmer (Z = 200 R^1,6) er et estimat.
Kræver: numpy, h5py, pillow, pyproj.
"""
import io, json, math, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

DMI = "https://opendataapi.dmi.dk"
UA = "dagens-oversigt/1.0 (+https://github.com/wghmnyg6tj-jpg/dr-rss)"
HALF_KM = 100
SIZE = 360
# (fra dBZ, farve, betegnelse)
LEVELS = [(10, (158, 202, 233), "let"), (20, (61, 143, 209), "let til moderat"), (30, (46, 158, 79), "moderat"),
          (40, (242, 140, 40), "kraftig"), (50, (215, 38, 61), "meget kraftig")]


def get(url, tries=4, binary=False, timeout=60):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*" if binary else "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return b if binary else json.loads(b.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and n < tries - 1:
                time.sleep(2 ** (n + 1))
                continue
            raise


def attrs(g):
    out = {}
    for k, v in g.attrs.items():
        if hasattr(v, "tolist"):
            v = v.tolist()
        if isinstance(v, list) and len(v) == 1:
            v = v[0]
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        out[k] = v
    return out


META = {}


def mmh(dbz):
    return (10 ** (dbz / 10) / 200) ** (1 / 1.6)


def main():
    import numpy as np, h5py
    from PIL import Image, ImageDraw
    from pyproj import Proj

    try:
        L = json.load(open("locations.json", encoding="utf-8"))
        p0 = [p for p in L.get("places", []) if p.get("lat") is not None][0]
    except Exception:
        p0 = {"name": "Mørkhøj", "lat": 55.74, "lon": 12.50}
    lat, lon, name = float(p0["lat"]), float(p0["lon"]), p0.get("name", "")
    meta = META
    meta.update({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "place": name, "lat": lat, "lon": lon})

    since = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    j = get(f"{DMI}/v1/radardata/collections/composite/items?datetime={since}/..&limit=500")
    feats = j.get("features", [])
    if not feats:
        j = get(f"{DMI}/v1/radardata/collections/composite/items?limit=200")
        feats = j.get("features", [])

    def href(f):
        a = f.get("asset") or f.get("assets") or {}
        return (a.get("data") or {}).get("href", "")

    def dt(f):
        return (f.get("properties") or {}).get("datetime", "")

    feats = [f for f in feats if href(f).endswith(".h5")]
    if not feats:
        raise SystemExit("ingen radarfiler fundet")
    pref = [f for f in feats if "500_max" in href(f)] or feats
    f = max(pref, key=dt)
    meta["file"] = href(f).rsplit("/", 1)[-1]
    meta["time"] = dt(f)
    meta["props"] = {k: v for k, v in (f.get("properties") or {}).items() if isinstance(v, (str, int, float))}

    data = get(href(f), binary=True, timeout=120)
    with h5py.File(io.BytesIO(data), "r") as h:
        grp = None
        for ds in sorted(k for k in h.keys() if k.startswith("dataset")):
            for dk in sorted(k for k in h[ds].keys() if k.startswith("data")):
                if "data" in h[ds][dk]:
                    grp = h[ds][dk]
                    break
            if grp is not None:
                break
        if grp is None:
            raise SystemExit("ukendt HDF5-struktur: " + ",".join(h.keys()))
        raw = grp["data"][:].astype("float64")
        what = attrs(grp["what"]) if "what" in grp else {}
        where = attrs(h["where"]) if "where" in h else {}
        topwhat = attrs(h["what"]) if "what" in h else {}
    meta["odim"] = {"what": what, "where": {k: v for k, v in where.items() if k != "projdef"}, "projdef": where.get("projdef"), "top": topwhat,
                    "shape": list(raw.shape), "raw_min": float(raw.min()), "raw_max": float(raw.max())}
    def fnum(v, d):
        if isinstance(v, (list, tuple)):
            v = v[0] if v else d
        return float(v) if v is not None else d
    gain, offset = fnum(what.get("gain"), 1.0), fnum(what.get("offset"), 0.0)
    nodata, undetect = what.get("nodata"), what.get("undetect")
    dbz = raw * gain + offset
    mask_nodata = (raw == nodata) if nodata is not None else np.zeros(raw.shape, bool)
    mask_none = (raw == undetect) if undetect is not None else np.zeros(raw.shape, bool)

    P = Proj(where["projdef"])
    xs, ys = float(where["xscale"]), float(where["yscale"])
    if "UL_lon" in where:
        x0, y0 = P(float(where["UL_lon"]), float(where["UL_lat"]))
    else:
        xll, yll = P(float(where["LL_lon"]), float(where["LL_lat"]))
        x0, y0 = xll, yll + raw.shape[0] * ys

    def pix(lo, la):
        x, y = P(lo, la)
        return (x - x0) / xs, (y0 - y) / ys

    cx, cy = pix(lon, lat)
    half = HALF_KM * 1000 / xs
    H, W = raw.shape
    if not (0 <= cx < W and 0 <= cy < H):
        meta["outside"] = True
        json.dump(meta, open("radar.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("Stedet ligger uden for DMI's radarbillede.")
        return 0
    c0, c1 = int(round(cx - half)), int(round(cx + half))
    r0, r1 = int(round(cy - half)), int(round(cy + half))

    img = np.zeros((r1 - r0, c1 - c0, 3), dtype=np.uint8)
    img[:] = (246, 243, 236)
    rr = np.arange(r0, r1)
    cc = np.arange(c0, c1)
    inside_r = (rr >= 0) & (rr < H)
    inside_c = (cc >= 0) & (cc < W)
    sub = np.full((len(rr), len(cc)), np.nan)
    nod = np.ones((len(rr), len(cc)), bool)
    ri, ci = np.where(inside_r)[0], np.where(inside_c)[0]
    if len(ri) and len(ci):
        block = dbz[rr[ri][0]:rr[ri][-1] + 1, cc[ci][0]:cc[ci][-1] + 1]
        bn = mask_nodata[rr[ri][0]:rr[ri][-1] + 1, cc[ci][0]:cc[ci][-1] + 1]
        bu = mask_none[rr[ri][0]:rr[ri][-1] + 1, cc[ci][0]:cc[ci][-1] + 1]
        blk = np.where(bu, np.nan, block)
        sub[ri[0]:ri[-1] + 1, ci[0]:ci[-1] + 1] = np.where(bn, np.nan, blk)
        nod[ri[0]:ri[-1] + 1, ci[0]:ci[-1] + 1] = bn
    img[nod] = (226, 222, 214)
    for lo, col, _ in LEVELS:
        img[np.nan_to_num(sub, nan=-99) >= lo] = col

    im = Image.fromarray(img, "RGB").resize((SIZE, SIZE), Image.NEAREST)
    d = ImageDraw.Draw(im)
    k = SIZE / (c1 - c0)

    def to_img(lo, la):
        px, py = pix(lo, la)
        return ((px - c0) * k, (py - r0) * k)

    try:
        coast = json.load(open("dk_coast.json", encoding="utf-8"))["lines"]
        for line in coast:
            pts = [to_img(a, b) for a, b in line]
            if any(-50 <= x <= SIZE + 50 and -50 <= y <= SIZE + 50 for x, y in pts):
                d.line(pts, fill=(90, 90, 90), width=1)
    except Exception as e:
        meta["coast_error"] = str(e)
    mx, my = to_img(lon, lat)
    for rad_km in (25, 50):
        r = rad_km * 1000 / xs * k
        d.ellipse([mx - r, my - r, mx + r, my + r], outline=(150, 150, 150), width=1)
    d.ellipse([mx - 5, my - 5, mx + 5, my + 5], fill=(200, 30, 45), outline=(255, 255, 255), width=2)
    im = im.convert("P", palette=Image.ADAPTIVE, colors=64)
    im.save("radar.png", optimize=True)

    # Nedbør tæt på stedet
    yy, xx = np.mgrid[0:len(rr), 0:len(cc)]
    dist_km = np.hypot((xx + c0 - cx) * xs, (yy + r0 - cy) * ys) / 1000
    near = {}
    for radius in (10, 25):
        vals = sub[(dist_km <= radius) & ~np.isnan(sub)]
        mxv = float(vals.max()) if vals.size else None
        near[str(radius)] = None if mxv is None or mxv < 10 else {"max_dbz": round(mxv, 1), "mm_h_estimat": round(mmh(mxv), 1),
                                                                  "niveau": [lvl for lo_, _, lvl in LEVELS if mxv >= lo_][-1]}
    meta.update({"half_km": HALF_KM, "size": SIZE, "near": near, "nodata_share": round(float(nod.mean()), 3),
                 "legend": [{"fra_dbz": lo, "farve": "#%02x%02x%02x" % col, "niveau": lvl} for lo, col, lvl in LEVELS]})
    json.dump(meta, open("radar.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Radar:", meta["time"], meta["file"], near)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        try:
            import traceback
            META.pop("near", None)
            META.update({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "error": f"{type(e).__name__}: {e}"[:300],
                         "trace": traceback.format_exc()[-1200:]})
            json.dump(META, open("radar.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        except Exception:
            pass
        print("Radar fejlede:", e)
        sys.exit(1)
