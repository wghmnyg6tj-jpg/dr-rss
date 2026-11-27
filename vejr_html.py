"""Skriver vejret ind på Dagens oversigt ud fra weather.json. Ingen tal skrives i hånden.

Brug:  python3 -I vejr_html.py side.html weather.json [--now 2026-11-27T13:33]
Ændrer side.html på stedet:
- .ov-stats: målt temperatur og vind (DMI-station), nedbør næste time (met.no)
- vejrteksten (det ene Fakta-afsnit i .wx-now)
- tidslinjen: præcis 24 timer fra det første hele klokkeslæt efter nu (met.no, DMI som reserve)
- overskriften i .tl-head
- afsnittet "Vejr:" i "Redaktionen mangler"
Skriver en kort JSON-opsummering til stdout.
Exit 0 = ok. Exit 2 = weather.json mangler, er for gammel eller dækker ikke de 24 timer (brug den gamle metode).
"""
import json, re, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Copenhagen")
MAX_AGE_MIN = 60
OBS_MAX_AGE_MIN = 40
DAY = ["Man", "Tirs", "Ons", "Tors", "Fre", "Lør", "Søn"]
DAYL = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MN = ["", "jan.", "feb.", "mar.", "apr.", "maj", "jun.", "jul.", "aug.", "sep.", "okt.", "nov.", "dec."]
DIRS = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
DIRL = ["nord", "nordøst", "øst", "sydøst", "syd", "sydvest", "vest", "nordvest"]

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


def num(x, d=1):
    a = f"{abs(x):.{d}f}"
    return ("−" if x < 0 and float(a) != 0 else "") + a.replace(".", ",")


def deg(x, d=1):
    return num(x, d) + "°"


def rint(x):
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def comp(wd, long=False):
    i = int(((wd % 360) / 45) + 0.5) % 8
    return (DIRL if long else DIRS)[i]


def mm_txt(x):
    return "0 mm" if x is None or x < 0.05 else num(x) + " mm"


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


def dkdate(dt, with_day=False):
    s = f"{dt.day}. {MN[dt.month]}"
    return (DAYL[dt.weekday()] + " " + s) if with_day else s


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
    met = (W.get("metno") or {}).get("hours", {})
    dmi = (W.get("dmi_forecast") or {}).get("hours", {})

    first = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    cells, used = [], []
    for i in range(24):
        t = first + timedelta(hours=i)
        k = key(t)
        if k in met and met[k].get("t2") is not None:
            m = met[k]
            ic, sky, kind = parse_sym(m["sym"])
            t2, ws, wd, mm, src = m["t2"], m["ws"], m["wd"], m.get("mm"), "met.no"
        elif k in dmi and dmi[k].get("t2") is not None:
            d = dmi[k]
            ic, sky, kind = dmi_sym(d, t.hour)
            t2, ws, wd, mm, src = d["t2"], d["ws"], d["wd"], d.get("mm"), "DMI"
        else:
            print(json.dumps({"ok": False, "fejl": f"ingen prognose for {k}"}, ensure_ascii=False))
            return 2
        used.append(src)
        if mm is None or mm < 0.05:
            rain = "Tørt"
        else:
            rain = {"sne": "Sne", "slud": "Slud"}.get(kind, "Regn") + " " + num(mm) + " mm"
        label = ("Nu " if i == 0 else (DAY[t.weekday()] + " " if t.hour == 0 else "")) + t.strftime("%H:%M")
        cells.append('<li class="tl-c%s"><span class="tl-h">%s</span><span class="tl-i">%s</span>'
                     '<span class="tl-t">%s</span><span class="tl-s">%s</span><span class="tl-r">%s</span>'
                     '<span class="tl-w">%s, %d m/s</span></li>' % (
                         " now" if i == 0 else "", label, ICON[ic], str(rint(t2)).replace("-", "−") + "°",
                         sky, rain, comp(wd), rint(ws)))
    last = first + timedelta(hours=23)
    if used.count("DMI"):
        warn.append(f"{used.count('DMI')} timer i tidslinjen er fra DMI, fordi met.no manglede dem")

    # Målinger: nærmeste station med frisk værdi
    obs = W.get("observations") or {}
    def pick(param):
        for sid in ("06181", "06180", "06186"):
            v = (obs.get(sid) or {}).get("values", {}).get(param)
            if v and v.get("value") is not None:
                ot = loc(v["observed"])
                if (now - ot).total_seconds() / 60 <= OBS_MAX_AGE_MIN:
                    return sid, obs[sid]["name"], v["value"], ot
        return None
    tobs = pick("temp_dry")
    wsobs, wdobs = pick("wind_speed"), pick("wind_dir")
    cur_k = key(now.replace(minute=0, second=0, microsecond=0))
    cur = met.get(cur_k) or met.get(key(first)) or {}
    if tobs:
        big = deg(tobs[2])
        where = f"Målt i {tobs[1]} kl. {hm(tobs[3])}"
    else:
        c0 = met.get(key(first)) or dmi.get(key(first)) or {}
        big = deg(c0.get("t2", 0))
        where = "Prognose (ingen frisk måling)"
        warn.append("ingen frisk DMI-måling; temperatur nu er fra prognosen")
    if wsobs and wdobs and wsobs[0] == wdobs[0]:
        wind_now = f"{comp(wdobs[2])}, {rint(wsobs[2])} m/s"
    else:
        wind_now = f"{comp(cur.get('wd', 0))}, {rint(cur.get('ws', 0))} m/s"
    pm = cur.get("mm")
    pnext = "Tørt næste time" if pm is None or pm < 0.05 else f"{num(pm)} mm næste time"
    stats = (f'<div class="ov-stats"><span class="big">{big}</span><span class="u">{pnext}</span>'
             f'<span class="u">{wind_now}</span><span class="u">{where}</span></div>')

    # Vejrtekst
    hrs = [first + timedelta(hours=i) for i in range(24)]
    def tot(src):
        vals = [src.get(key(t), {}).get("mm") for t in hrs]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None
    m24, d24 = tot(met), tot(dmi)
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
        def wtype(src):
            ws_ = [src.get(key(t)) for t in win[:2]]
            ws_ = [w for w in ws_ if w]
            mmw = sum((w.get("mm") or 0) for w in ws_)
            if mmw < 0.05:
                return "tørt", mmw
            if src is met:
                kinds = [parse_sym(w["sym"])[2] for w in ws_ if (w.get("mm") or 0) >= 0.05]
            else:
                kinds = [w.get("ptype") for w in ws_ if (w.get("mm") or 0) >= 0.05]
            k = next((x for x in kinds if x), "regn")
            return k, mmw
        mk, mmm = wtype(met)
        dk, dmm = wtype(dmi) if dmi else (None, None)
        if mk == "tørt" and dk in ("tørt", None):
            pr = "ingen regn eller sne" + (" i begge modeller" if dk else "")
        elif dk is None:
            pr = f"{mk} {mm_txt(mmm)} (met.no)"
        elif mk == dk:
            pr = f"{mk}: met.no {mm_txt(mmm)}, DMI {mm_txt(dmm)}"
        else:
            pr = f"met.no: {mk if mk != 'tørt' else 'tørt'}" + (f" {mm_txt(mmm)}" if mk != "tørt" else "") + \
                 f", DMI: {dk}" + (f" {mm_txt(dmm)}" if dk != "tørt" else "")
        parts.append(f"{dname} kl. 7–9: {deg(mw[0]['t2'])} → {deg(mw[2]['t2'])}, vind {num(min(wsl))}–{num(max(wsl))} m/s "
                     f"fra {comp(mw[1]['wd'])}, {pr}.")
    else:
        warn.append("morgenen kl. 7–9 ligger uden for met.no-data")
    mins = [(met[key(t)]["t2"], t) for t in hrs if key(t) in met]
    if mins:
        mn, mt = min(mins, key=lambda x: x[0])
        when = ("i dag" if mt.date() == now.date() else DAYL[mt.weekday()]) + f" kl. {mt.hour:02d}"
        s = f"Laveste {deg(mn)} {when}" + (" (frost)" if mn <= 0 else ", ingen frost i luften")
        g = [(dmi[key(t)]["t0"], t) for t in hrs if key(t) in dmi and dmi[key(t)].get("t0") is not None]
        if g:
            gmn, gt = min(g, key=lambda x: x[0])
            if gmn <= 0:
                s += f". DMI: jorden ned til {deg(gmn)} kl. {gt.hour:02d}, så glatte veje er mulige"
        dm = [(dmi[key(t)]["t2"], t) for t in hrs if key(t) in dmi and dmi[key(t)].get("t2") is not None]
        if dm:
            dmn = min(x[0] for x in dm)
            if abs(dmn - mn) >= 1.5:
                s += f". Uenighed: DMI har laveste {deg(dmn)}"
        parts.append(s + ".")
    if m24 is not None and d24 is not None and ((m24 >= 0.5 and d24 < 0.1) or (d24 >= 0.5 and m24 < 0.1)):
        parts.append("Modellerne er uenige om, hvorvidt det bliver vådt.")
    lg = W.get("lightning") or {}
    if lg.get("count_last_hour"):
        parts.append(f"DMI har målt {lg['count_last_hour']} lyn i området den seneste time.")
    text = '<p><span class="tag fakta">Fakta</span> ' + " ".join(parts) + "</p>"

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
    s, nh = re.subn(r'(<div class="tl-head"><span class="l">)[^<]*(</span>)', lambda m: m.group(1) + head + m.group(2), s, count=1)
    s, ns = re.subn(r'<div class="ov-stats">.*?</div>', lambda m: stats, s, count=1, flags=re.S)
    # vejrteksten: første <p> med Fakta-mærke inde i .wx-now
    wa = s.find('wx-now')
    we = s.find('<div class="tl"', wa)
    seg = s[wa:we]
    seg2, nt = re.subn(r'<p><span class="tag fakta">Fakta</span>.*?</p>', lambda m: text, seg, count=1, flags=re.S)
    if nt == 0:
        seg2 = seg.replace("</div>", text + "</div>", 1) if "</div>" in seg else seg
    s = s[:wa] + seg2 + s[we:]
    # "Vejr:" i Redaktionen mangler
    dm_run = (W.get("dmi_forecast") or {}).get("run")
    run_txt = ""
    if dm_run:
        rr = datetime.strptime(dm_run, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        run_txt = f" DMI HARMONIE: kørsel kl. {hm(rr)}."
    mu = (W.get("metno") or {}).get("updated_at")
    st = W.get("status", {})
    bad = [f"{k} ({v})" for k, v in st.items() if v != "ok"]
    vejr = (f'<p><b>Vejr:</b> Bygget af vejr_html.py ud fra weather.json (hentet af GitHub kl. {hm(gen)}). '
            f'met.no-modellen opdateret kl. {hm(loc(mu)) if mu else "ukendt"}.{run_txt} '
            f'Temperatur nu: {where.lower() if tobs else "ingen frisk måling, prognose brugt"}. '
            f'Tidslinje: {first.day}. {MN[first.month]} kl. {first.hour:02d} til {last.day}. {MN[last.month]} kl. {last.hour:02d}'
            f' ({"met.no" if "DMI" not in used else "met.no og DMI"}).'
            + (f' Kilder med fejl: {", ".join(bad)}.' if bad else "") + "</p>")
    s, nv = re.subn(r'<p><b>Vejr:</b>.*?</p>', lambda m: vejr, s, count=1, flags=re.S)
    if nv == 0:
        s = re.sub(r'(<section class="miss"[^>]*>\s*<h2>[^<]*</h2>)', lambda m: m.group(1) + vejr, s, count=1)
    open(page_f, "w", encoding="utf-8").write(s)
    print(json.dumps({"ok": True, "celler": len(cells), "foerste": first.strftime("%Y-%m-%d %H:%M"),
                      "sidste": last.strftime("%Y-%m-%d %H:%M"), "temperatur_nu": big, "maaling": where,
                      "weather_json_alder_min": round(age), "metno_opdateret": hm(loc(mu)) if mu else None,
                      "dmi_koersel": dm_run, "advarsler": warn, "tekst": re.sub(r"<[^>]+>", "", text)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
