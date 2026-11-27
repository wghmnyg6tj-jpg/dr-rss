"""Skriver vejret ind på Dagens oversigt ud fra weather.json (og radar.json/radar.png). Ingen tal skrives i hånden.

Brug:  python3 -I vejr_html.py side.html weather.json [--now 2026-11-27T13:33]
radar.json og radar.png læses fra samme mappe som weather.json.
Ændrer side.html på stedet:
- overskriften i .wx-now efter hovedområdet (Indstillinger)
- .ov-stats: målt temperatur og vind (nærmeste DMI-station), nedbør næste time (met.no)
- vejrteksten (det ene Fakta-afsnit i .wx-now)
- #wx-more: kort linje for hvert ekstra område
- #wx-places (skjult): de områder, der bruges nu (læses af settings.html)
- tidslinjen: præcis 24 timer fra det første hele klokkeslæt efter nu (met.no, DMI som reserve),
  med DMI's nedbør i hver time
- overskriften i .tl-head
- #wx-radar: radarbillede fra DMI omkring hovedområdet (kun hvis det er højst 45 min gammelt)
- afsnittet "Vejr:" i "Redaktionen mangler"
Skriver en kort JSON-opsummering til stdout.
Exit 0 = ok. Exit 2 = weather.json mangler, er for gammel eller dækker ikke de 24 timer (brug den gamle metode).
"""
import base64, html, json, os, re, sys, unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Copenhagen")
MAX_AGE_MIN = 60
OBS_MAX_AGE_MIN = 40
RADAR_MAX_AGE_MIN = 45
DAY = ["Man", "Tirs", "Ons", "Tors", "Fre", "Lør", "Søn"]
DAYL = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MN = ["", "jan.", "feb.", "mar.", "apr.", "maj", "jun.", "jul.", "aug.", "sep.", "okt.", "nov.", "dec."]
DIRS = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]

CLOUD = '<path class="cl" d="M13 35h22a7.5 7.5 0 0 0 .9-14.95A10.5 10.5 0 0 0 16 18.4 8.8 8.8 0 0 0 13 35z"/>'
CLOUD_S = '<path class="cl" transform="translate(3,6) scale(.88)" d="M13 35h22a7.5 7.5 0 0 0 .9-14.95A10.5 10.5 0 0 0 16 18.4 8.8 8.8 0 0 0 13 35z"/>'
CLOUD_UP = '<path class="cl" d="M13 29h22a7.5 7.5 0 0 0 .9-14.95A10.5 10.5 0 0 0 16 12.4 8.8 8.8 0 0 0 13 29z"/>'


def svg(x):
    return '<svg viewBox="0 0 48 40" width="40" height="34" aria-hidden="true" focusable="false">%s</svg>' % x


ICON = {
    "sun": svg('<circle class="su" cx="24" cy="20" r="9"/>'),
    "moon": svg('<path class="mo" d="M30 8a12 12 0 1 0 10 19 10 10 0 0 1-10-19z"/>'),
    "sun_cloud": svg('<circle class="su" cx="31" cy="12" r="7"/>' + CLOUD_S),
    "moon_cloud": svg('<path class="mo" d="M31 3a10 10 0 1 0 11 14 8.5 8.5 0 0 1-11-14z"/>' + CLOUD_S),
    "cloud": svg(CLOUD),
    "rain": svg(CLOUD_UP + '<g class="sn"><line x1="17" y1="32" x2="15" y2="37"/><line x1="25" y1="32" x2="23" y2="37"/><line x1="33" y1="32" x2="31" y2="37"/></g>'),
    "snow": svg('<g class="sn"><line x1="24" y1="6" x2="24" y2="34"/><line x1="10" y1="13" x2="38" y2="27"/><line x1="10" y1="27" x2="38" y2="13"/></g>'),
}
E = html.escape


def num(x, d=1):
    a = f"{abs(x):.{d}f}"
    return ("−" if x < 0 and float(a) != 0 else "") + a.replace(".", ",")


def deg(x, d=1):
    return num(x, d) + "°"


def rint(x):
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def comp(wd):
    return DIRS[int(((wd % 360) / 45) + 0.5) % 8]


def mm_txt(x):
    return "0 mm" if x is None or x < 0.05 else num(x) + " mm"


def norm(s):
    return unicodedata.normalize("NFC", str(s or "")).strip().lower()


def parse_sym(sym):
    n = sym.split("_")[0]
    night = sym.endswith("_night")
    if "thunder" in n:
        return "rain", "Torden", "regn"
    if "sleet" in n:
        return "rain", "Slud", "slud"
    if "snow" in n:
        return "snow", ("Let sne" if "light" in n else "Kraftig sne" if "heavy" in n else "Sne"), "sne"
    if "rain" in n:
        return "rain", ("Let regn" if "light" in n else "Kraftig regn" if "heavy" in n else "Regn"), "regn"
    if n == "fog":
        return "cloud", "Tåge", None
    if n == "clearsky":
        return ("moon", "Klart", None) if night else ("sun", "Solrigt", None)
    if n == "fair":
        return ("moon", "Næsten klart", None) if night else ("sun", "Mest solrigt", None)
    if n == "partlycloudy":
        return ("moon_cloud" if night else "sun_cloud"), "Delvist skyet", None
    return "cloud", "Overskyet", None


def dmi_sym(h, local_hour):
    """Reserve når met.no mangler en time: ikon ud fra DMI's skydække og nedbørstype."""
    night = local_hour < 7 or local_hour >= 17
    if h.get("mm") is not None and h["mm"] >= 0.05:
        pt = h.get("ptype") or "regn"
        if pt in ("sne", "kornsne"):
            return "snow", "Sne", "sne"
        if pt == "slud":
            return "rain", "Slud", "slud"
        return "rain", pt.capitalize(), "regn"
    c = h.get("cloud")
    if c is None or c >= 0.8:
        return "cloud", "Overskyet", None
    if c >= 0.3:
        return ("moon_cloud" if night else "sun_cloud"), "Delvist skyet", None
    return ("moon" if night else "sun"), ("Klart" if night else "Solrigt"), None


def key(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")


def loc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ)


def hm(dt):
    return dt.strftime("%H:%M")


def when_txt(t, now):
    return ("i dag" if t.date() == now.date() else DAYL[t.weekday()]) + f" kl. {t.hour:02d}"


def places_from(W):
    """weather.json version 2 (places) eller version 1 (ét sted)."""
    if W.get("places"):
        return W["places"]
    obs = W.get("observations") or {}
    st = {k: v for k, v in obs.items() if isinstance(v, dict) and "values" in v}
    return [{"name": "Mørkhøj", "lat": 55.74, "lon": 12.50, "metno": W.get("metno") or {},
             "dmi_forecast": W.get("dmi_forecast") or {}, "observations": {"stations": st}, "status": W.get("status", {})}]


def stations(P):
    st = ((P.get("observations") or {}).get("stations")) or {}
    return sorted(st.items(), key=lambda kv: kv[1].get("dist_km", 999))


def pick(P, param, now):
    for sid, s in stations(P):
        v = (s.get("values") or {}).get(param)
        if v and v.get("value") is not None:
            ot = loc(v["observed"])
            if (now - ot).total_seconds() / 60 <= OBS_MAX_AGE_MIN:
                return sid, s, v["value"], ot
    return None


def summary_24h(P, hrs):
    met = (P.get("metno") or {}).get("hours", {})
    dmi = (P.get("dmi_forecast") or {}).get("hours", {})

    def tot(src):
        vals = [src.get(key(t), {}).get("mm") for t in hrs]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None
    mins = [(met[key(t)]["t2"], t) for t in hrs if key(t) in met and met[key(t)].get("t2") is not None]
    g = [(dmi[key(t)]["t0"], t) for t in hrs if key(t) in dmi and dmi[key(t)].get("t0") is not None]
    return {"m24": tot(met), "d24": tot(dmi), "min": min(mins, key=lambda x: x[0]) if mins else None,
            "gmin": min(g, key=lambda x: x[0]) if g else None}


def main(argv):
    if len(argv) < 3:
        print("Brug: vejr_html.py side.html weather.json [--now ISO]", file=sys.stderr)
        return 1
    page_f, w_f = argv[1], argv[2]
    now = datetime.now(TZ)
    if "--now" in argv:
        now = datetime.fromisoformat(argv[argv.index("--now") + 1]).replace(tzinfo=TZ)
    warn = []
    try:
        W = json.load(open(w_f, encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"ok": False, "fejl": f"weather.json kan ikke læses: {e}"}, ensure_ascii=False))
        return 2
    gen = loc(W["generated"])
    age = (now - gen).total_seconds() / 60
    if age > MAX_AGE_MIN:
        print(json.dumps({"ok": False, "fejl": f"weather.json er {round(age)} min gammel"}, ensure_ascii=False))
        return 2
    PL = places_from(W)
    P0 = PL[0]
    pname = P0.get("name") or "Mørkhøj"
    met = (P0.get("metno") or {}).get("hours", {})
    dmi = (P0.get("dmi_forecast") or {}).get("hours", {})

    # Tidslinje
    first = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    hrs = [first + timedelta(hours=i) for i in range(24)]
    cells, used = [], []
    for i, t in enumerate(hrs):
        k = key(t)
        if k in met and met[k].get("t2") is not None:
            m = met[k]
            ic, sky, kind = parse_sym(m["sym"])
            t2, ws, wd, mm = m["t2"], m["ws"], m["wd"], m.get("mm")
            used.append("met.no")
        elif k in dmi and dmi[k].get("t2") is not None:
            d = dmi[k]
            ic, sky, kind = dmi_sym(d, t.hour)
            t2, ws, wd, mm = d["t2"], d["ws"], d["wd"], d.get("mm")
            used.append("DMI")
        else:
            print(json.dumps({"ok": False, "fejl": f"ingen prognose for {k}"}, ensure_ascii=False))
            return 2
        rain = "Tørt" if mm is None or mm < 0.05 else {"sne": "Sne", "slud": "Slud"}.get(kind, "Regn") + " " + num(mm) + " mm"
        dh = dmi.get(k)
        if not dh or dh.get("mm") is None:
            dtx = "DMI: –"
        elif dh["mm"] < 0.05:
            dtx = "DMI: tørt"
        else:
            dtx = f"DMI: {dh.get('ptype') or 'nedbør'} {num(dh['mm'])} mm"
        label = ("Nu " if i == 0 else (DAY[t.weekday()] + " " if t.hour == 0 else "")) + t.strftime("%H:%M")
        cells.append('<li class="tl-c%s"><span class="tl-h">%s</span><span class="tl-i">%s</span>'
                     '<span class="tl-t">%s</span><span class="tl-s">%s</span><span class="tl-r">%s</span>'
                     '<span class="tl-d" style="display:block;font-size:.68rem;opacity:.75">%s</span>'
                     '<span class="tl-w">%s, %d m/s</span></li>' % (
                         " now" if i == 0 else "", label, ICON[ic], str(rint(t2)).replace("-", "−") + "°",
                         sky, rain, E(dtx), comp(wd), rint(ws)))
    last = hrs[-1]
    if "DMI" in used:
        warn.append(f"{used.count('DMI')} timer i tidslinjen er fra DMI, fordi met.no manglede dem")

    # Nu
    tobs, wsobs, wdobs = pick(P0, "temp_dry", now), pick(P0, "wind_speed", now), pick(P0, "wind_dir", now)
    cur = met.get(key(now.replace(minute=0, second=0, microsecond=0))) or met.get(key(first)) or {}
    if tobs:
        big = deg(tobs[2])
        where = f"Målt i {tobs[1]['name']} ({num(tobs[1].get('dist_km', 0))} km væk) kl. {hm(tobs[3])}"
    else:
        c0 = met.get(key(first)) or dmi.get(key(first)) or {}
        big = deg(c0.get("t2", 0))
        where = "Prognose (ingen frisk DMI-måling i nærheden)"
        warn.append("ingen frisk DMI-måling; temperatur nu er fra prognosen")
    if wsobs and wdobs and wsobs[0] == wdobs[0]:
        wind_now = f"{comp(wdobs[2])}, {rint(wsobs[2])} m/s"
    else:
        wind_now = f"{comp(cur.get('wd', 0))}, {rint(cur.get('ws', 0))} m/s"
    pm = cur.get("mm")
    pnext = "Tørt næste time" if pm is None or pm < 0.05 else f"{num(pm)} mm næste time"
    stats = (f'<div class="ov-stats"><span class="big">{big}</span><span class="u">{pnext}</span>'
             f'<span class="u">{wind_now}</span><span class="u">{E(where)}</span></div>')

    # Vejrtekst for hovedområdet
    S0 = summary_24h(P0, hrs)
    m24, d24 = S0["m24"], S0["d24"]
    parts = []
    if (m24 or 0) < 0.1 and (d24 is None or d24 < 0.1):
        parts.append("Tørt de næste 24 timer i både met.no og DMI." if d24 is not None else f"Tørt de næste 24 timer i met.no ({mm_txt(m24)}).")
    else:
        parts.append(f"Nedbør de næste 24 timer: met.no {mm_txt(m24)}, DMI {mm_txt(d24)}.")
    day = now.date() if now.hour < 7 else (now + timedelta(days=1)).date()
    m7 = datetime(day.year, day.month, day.day, 7, tzinfo=TZ)
    win = [m7, m7 + timedelta(hours=1), m7 + timedelta(hours=2)]
    mw = [met.get(key(t)) for t in win]
    if all(mw):
        wsl = [x["ws"] for x in mw]
        dname = "I dag" if m7.date() == now.date() else DAYL[m7.weekday()].capitalize()

        def wtype(src, is_met):
            ws_ = [w for w in (src.get(key(t)) for t in win[:2]) if w]
            mmw = sum((w.get("mm") or 0) for w in ws_)
            if not ws_:
                return None, None
            if mmw < 0.05:
                return "tørt", mmw
            kinds = [(parse_sym(w["sym"])[2] if is_met else w.get("ptype")) for w in ws_ if (w.get("mm") or 0) >= 0.05]
            return next((x for x in kinds if x), "regn"), mmw
        mk, mmm = wtype(met, True)
        dk, dmm = wtype(dmi, False)
        if mk == "tørt" and dk in ("tørt", None):
            pr = "ingen regn eller sne" + (" (begge modeller)" if dk else " (met.no)")
        elif dk is None:
            pr = f"{mk} {mm_txt(mmm)} (met.no)"
        elif mk == dk:
            pr = f"{mk}: met.no {mm_txt(mmm)}, DMI {mm_txt(dmm)}"
        else:
            pr = (f"met.no: {mk}" + (f" {mm_txt(mmm)}" if mk != "tørt" else "") +
                  f", DMI: {dk}" + (f" {mm_txt(dmm)}" if dk != "tørt" else ""))
        parts.append(f"{dname} kl. 7–9: {deg(mw[0]['t2'])} → {deg(mw[2]['t2'])}, vind {num(min(wsl))}–{num(max(wsl))} m/s "
                     f"fra {comp(mw[1]['wd'])}, {pr}.")
    else:
        warn.append("morgenen kl. 7–9 ligger uden for met.no-data")
    if S0["min"]:
        mn, mt = S0["min"]
        s = f"Laveste {deg(mn)} {when_txt(mt, now)}" + (" (frost)" if mn <= 0 else ", ingen frost i luften")
        if S0["gmin"] and S0["gmin"][0] <= 0:
            s += f". DMI: jorden ned til {deg(S0['gmin'][0])} {when_txt(S0['gmin'][1], now)}, så glatte veje er mulige"
        dm = [dmi[key(t)]["t2"] for t in hrs if key(t) in dmi and dmi[key(t)].get("t2") is not None]
        if dm and abs(min(dm) - mn) >= 1.5:
            s += f". Uenighed: DMI har laveste {deg(min(dm))}"
        parts.append(s + ".")
    if m24 is not None and d24 is not None and ((m24 >= 0.5 and d24 < 0.1) or (d24 >= 0.5 and m24 < 0.1)):
        parts.append("Modellerne er uenige om, hvorvidt det bliver vådt.")
    lg = W.get("lightning") or {}
    if lg.get("count_last_hour"):
        parts.append(f"DMI har målt {lg['count_last_hour']} lyn i området den seneste time.")
    text = '<p><span class="tag fakta">Fakta</span> ' + E(" ".join(parts), quote=False) + "</p>"

    # Ekstra områder
    rows = []
    for P in PL[1:]:
        S = summary_24h(P, hrs)
        o = pick(P, "temp_dry", now)
        bits = []
        if o:
            bits.append(f"{deg(o[2])} målt i {o[1]['name']} ({num(o[1].get('dist_km', 0))} km) kl. {hm(o[3])}")
        else:
            pm_ = (P.get("metno") or {}).get("hours", {}).get(key(first))
            if pm_:
                bits.append(f"{deg(pm_['t2'])} kl. {first.hour:02d} (prognose)")
        if S["m24"] is not None or S["d24"] is not None:
            bits.append(f"næste 24 t: met.no {mm_txt(S['m24'])}" + (f", DMI {mm_txt(S['d24'])}" if S["d24"] is not None else ", DMI dækker ikke stedet"))
        if S["min"]:
            bits.append(f"laveste {deg(S['min'][0])} {when_txt(S['min'][1], now)}")
        if S["gmin"] and S["gmin"][0] <= 0:
            bits.append(f"jorden ned til {deg(S['gmin'][0])} (DMI)")
        if not bits:
            bits.append("ingen data")
        rows.append(f'<li><b>{E(P.get("name") or "")}</b> · {E(" · ".join(bits), quote=False)}</li>')
    more = ('<div class="wx-more" id="wx-more">' + (
        '<ul style="list-style:none;margin:8px 0 0;padding:0;font-size:.85rem;line-height:1.5">' + "".join(rows) + "</ul>" if rows else "") + "</div>")
    pdata = [{"name": P.get("name"), "lat": P.get("lat"), "lon": P.get("lon"), "found": P.get("found")} for P in PL]
    places_div = ('<div id="wx-places" hidden data-places="' + E(json.dumps(pdata, ensure_ascii=False)) +
                  '" data-errors="' + E(json.dumps(W.get("location_errors", []), ensure_ascii=False)) + '"></div>')

    # Radar
    rdir = os.path.dirname(os.path.abspath(w_f))
    radar_html, radar_note = "", "Radar: ikke tilgængelig."
    try:
        R = json.load(open(os.path.join(rdir, "radar.json"), encoding="utf-8"))
        if R.get("error"):
            radar_note = f"Radar: fejl ved seneste hentning ({R['error'][:80]})."
        elif R.get("outside"):
            radar_note = f"Radar: DMI's radar dækker ikke {pname}."
        elif R.get("near") is not None and R.get("time"):
            rt = loc(R["time"])
            rage = (now - rt).total_seconds() / 60
            same = abs(float(R.get("lat", 0)) - float(P0.get("lat", 0))) < 0.01 and abs(float(R.get("lon", 0)) - float(P0.get("lon", 0))) < 0.01
            if not same:
                radar_note = "Radar: billedet er endnu ikke lavet for det nye hovedområde."
            elif rage > RADAR_MAX_AGE_MIN:
                radar_note = f"Radar: seneste billede er fra kl. {hm(rt)} ({round(rage)} min gammelt) og vises ikke."
            else:
                png = base64.b64encode(open(os.path.join(rdir, "radar.png"), "rb").read()).decode("ascii")
                n10, n25 = R["near"].get("10"), R["near"].get("25")
                if n10:
                    near_txt = f"Nedbør inden for 10 km: {n10['niveau']} (op til ca. {num(n10['mm_h_estimat'])} mm/t, estimat)."
                elif n25:
                    near_txt = f"Ingen nedbør inden for 10 km. 10–25 km væk: {n25['niveau']} (op til ca. {num(n25['mm_h_estimat'])} mm/t, estimat)."
                else:
                    near_txt = "Ingen nedbør på radaren inden for 25 km."
                chips = "".join(f'<span style="display:inline-block;width:10px;height:10px;background:{E(l["farve"])};'
                                f'border-radius:2px;margin:0 3px 0 8px;vertical-align:middle"></span>{E(l["niveau"])}'
                                for l in R.get("legend", []))
                radar_html = (
                    '<div class="wx-radar" id="wx-radar" style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin:14px 0 6px">'
                    f'<img src="data:image/png;base64,{png}" width="240" height="240" alt="Radarbillede fra DMI omkring {E(pname)} kl. {hm(rt)}" '
                    'style="width:240px;max-width:100%;height:auto;border:1px solid var(--rule);border-radius:4px">'
                    '<div style="flex:1;min-width:200px;font-size:.85rem;line-height:1.45">'
                    f'<p style="margin:0 0 6px"><b>Radar · DMI kl. {hm(rt)}</b> ({round(rage)} min gammelt)</p>'
                    f'<p style="margin:0 0 6px">{E(near_txt, quote=False)}</p>'
                    f'<p style="margin:0;font-size:.75rem;opacity:.85">Udsnit 200 × 200 km. Rød prik = {E(pname)}. Ringe = 25 og 50 km.<br>{chips}</p>'
                    '</div></div>')
                radar_note = f"Radar: DMI kl. {hm(rt)} ({round(rage)} min gammelt)."
    except FileNotFoundError:
        pass
    except Exception as e:
        radar_note = f"Radar: kunne ikke læses ({type(e).__name__})."
    if not radar_html:
        radar_html = '<div class="wx-radar" id="wx-radar" hidden></div>'

    # Skriv ind på siden
    s = open(page_f, encoding="utf-8").read()
    n_ol = s.count('<ol class="tl-scroll"')
    if n_ol != 1 or s.count('class="ov-stats"') != 1:
        print(json.dumps({"ok": False, "fejl": f"siden har {n_ol} tidslinjer og {s.count('class=\"ov-stats\"')} ov-stats; forventet 1 af hver"}, ensure_ascii=False))
        return 2
    a = s.index('<ol class="tl-scroll"')
    b = s.index("</ol>", a) + 5
    s = s[:a] + '<ol class="tl-scroll" tabindex="0" aria-label="Vejr time for time">' + "".join(cells) + "</ol>" + s[b:]
    head = (f"Tidslinje · Næste 24 timer ({first.day}. {MN[first.month]} kl. {first.hour:02d} "
            f"til {last.day}. {MN[last.month]} kl. {last.hour:02d})")
    s = re.sub(r'(<div class="tl-head"><span class="l">)[^<]*(</span>)', lambda m: m.group(1) + head + m.group(2), s, count=1)
    s = re.sub(r'<div class="ov-stats">.*?</div>', lambda m: stats, s, count=1, flags=re.S)
    # gamle ekstra-blokke fjernes, før de skrives på ny
    s = re.sub(r'<div class="wx-more" id="wx-more">.*?</div>', "", s, flags=re.S)
    s = re.sub(r'<div id="wx-places" hidden[^>]*></div>', "", s)
    wa = s.find("wx-now")
    we = s.find('<div class="tl"', wa)
    seg = s[wa:we]
    h2 = "Vejr · København og Mørkhøj" if norm(pname) == "mørkhøj" else f"Vejr · {E(pname)}"
    seg = re.sub(r"<h2>[^<]*</h2>", lambda m: f"<h2>{h2}</h2>", seg, count=1)
    seg, nt = re.subn(r'<p><span class="tag fakta">Fakta</span>.*?</p>', lambda m: text + more + places_div, seg, count=1, flags=re.S)
    if nt == 0:
        k = seg.rfind("</div>")
        seg = seg[:k] + text + more + places_div + seg[k:] if k >= 0 else seg + text + more + places_div
    s = s[:wa] + seg + s[we:]
    # radar
    if 'id="wx-radar"' in s:
        s = re.sub(r'<div class="wx-radar" id="wx-radar"[^>]*>(?:<img [^>]*>)?(?:<div [^>]*>.*?</div>)?</div>', lambda m: radar_html, s, count=1, flags=re.S)
    else:
        ti = s.find('<div class="threat"')
        if ti < 0:
            ti = s.find("</ol>", s.find('<ol class="tl-scroll"')) + 5
            ti = s.find("</div>", ti) + 6
        s = s[:ti] + radar_html + s[ti:]
    # "Vejr:" i Redaktionen mangler
    run_txt = ""
    dm_run = (P0.get("dmi_forecast") or {}).get("run")
    if dm_run:
        rr = datetime.strptime(dm_run, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        run_txt = f" DMI HARMONIE: kørsel kl. {hm(rr)}."
    mu = (P0.get("metno") or {}).get("updated_at")
    bad = [f"{k} ({v})" for k, v in (P0.get("status") or {}).items() if v != "ok"]
    for P in PL[1:]:
        bad += [f"{P.get('name')}: {k} ({v})" for k, v in (P.get("status") or {}).items() if v != "ok"]
    lerr = W.get("location_errors") or []
    names = ", ".join(E(P.get("name") or "") for P in PL)
    vejr = (f'<p><b>Vejr:</b> Bygget af vejr_html.py ud fra weather.json (hentet af GitHub kl. {hm(gen)}). '
            f'Områder: {names} (hovedområde: {E(pname)}). '
            f'met.no-modellen opdateret kl. {hm(loc(mu)) if mu else "ukendt"}.{run_txt} '
            f'Temperatur nu: {E(where)}. '
            f'Tidslinje: {first.day}. {MN[first.month]} kl. {first.hour:02d} til {last.day}. {MN[last.month]} kl. {last.hour:02d}'
            f' ({"met.no" if "DMI" not in used else "met.no og DMI"}, DMI-nedbør i hver time). {E(radar_note)}'
            + (f' Kilder med fejl: {E(", ".join(bad))}.' if bad else "")
            + (f' Områder, der ikke kunne findes: {E(", ".join(lerr))}.' if lerr else "") + "</p>")
    s, nv = re.subn(r'<p><b>Vejr:</b>.*?</p>', lambda m: vejr, s, count=1, flags=re.S)
    if nv == 0:
        s = re.sub(r'(<section class="miss"[^>]*>\s*<h2>[^<]*</h2>)', lambda m: m.group(1) + vejr, s, count=1)
    open(page_f, "w", encoding="utf-8").write(s)
    print(json.dumps({"ok": True, "celler": len(cells), "foerste": first.strftime("%Y-%m-%d %H:%M"),
                      "sidste": last.strftime("%Y-%m-%d %H:%M"), "hovedomraade": pname,
                      "ekstra_omraader": [P.get("name") for P in PL[1:]], "temperatur_nu": big, "maaling": where,
                      "weather_json_alder_min": round(age), "metno_opdateret": hm(loc(mu)) if mu else None,
                      "dmi_koersel": dm_run, "radar": radar_note, "advarsler": warn,
                      "tekst": re.sub(r"<[^>]+>", "", text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
