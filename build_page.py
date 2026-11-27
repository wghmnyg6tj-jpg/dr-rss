"""Bygger hele siden "Dagens oversigt" som én færdig fil: site/index.html.

Brug:  python3 build_page.py
Læser: template.html, feeds.json, extra.json, weather.json (+ radar.json/radar.png via vejr_html.py),
       outdoor_events.html og seen.json (hvornår hvert link blev set første gang).
Skriver: site/index.html, site/build.json og seen.json.

Ingen AI: overskrifter og korte resuméer kommer fra kildernes egne RSS-feeds.
Mine events og trusselsfeltet vises i browseren fra artifactens database (settings/calendar og settings/threat).
"""
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Copenhagen")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "site")
MAX_AGE_H = 168          # artikler ældre end 7 dage kommer ikke med (browseren filtrerer efter Indstillinger)
NEW_H = 2                # "Nyt" = set første gang inden for de seneste 2 timer
CAPS = {"danmark": 12, "indvandring": 10, "dagpenge": 10, "teknologi": 10, "ai": 10, "outdoor": 10, "foto": 10}
EN_SOURCES = {"PetaPixel", "Fuji Rumors", "Fstoppers", "Ars Technica", "The Verge", "TechCrunch", "The Neuron",
              "GearJunkie", "SectionHiker", "The Trek", "Outside", "Backpacker", "Copenhagen Post"}
RUMOR_SOURCES = {"Fuji Rumors"}
SOURCE_LABEL = {"BT": "B.T."}
RE_INDV = re.compile(r"indvandr|udlænding|asyl|flygtning|integration|migrant|migration|statsborgerskab|udvis|opholdstilladelse|"
                     r"familiesammenf|kærshovedgård|parallelsamfund|ghetto|immigra|refugee|asylum|deport", re.I)
RE_DAGP = re.compile(r"dagpenge|a-kasse|akasse|arbejdsløs|ledighed|ledige\b|kontanthjælp|jobcenter|beskæftigelse|efterløn|"
                     r"seniorpension|unemploy|jobless|hovedlov", re.I)
RE_NOHUNT = re.compile(r"\bhunt|hunting|fishing|\bfish\b|angler|rifle|shotgun|\bguns?\b|firearm|\bammo\b|jagt|jæger|fiskeri|"
                       r"\belk\b|deer season|bowhunt", re.I)
MON = ["jan.", "feb.", "mar.", "apr.", "maj", "jun.", "jul.", "aug.", "sep.", "okt.", "nov.", "dec."]
MONTH = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december"]
WEEKDAY = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
E = html.escape
SRC_STYLE = 'style="margin:6px 0 0;font-family:var(--ui);font-size:.66rem;color:var(--muted)"'
FEMPTY = ('<p class="assess fempty" hidden style="font-style:normal">Ingen nyheder inden for den maksimale alder. '
          'Vil du beholde ældre nyheder fremover, så hæv grænsen under Indstillinger.</p>')


def load(name, default=None):
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def loc(d):
    return d.astimezone(TZ)


def pubtxt(d, now):
    d = loc(d)
    if d.date() == now.date():
        return f"i dag kl. {d:%H:%M}"
    return f"{d.day}. {MON[d.month - 1]} kl. {d:%H:%M}"


def iso_local(d):
    return loc(d).isoformat(timespec="minutes")


def norm_title(t):
    return re.sub(r"[^a-zæøå0-9]+", " ", t.lower()).strip()


def safe_url(u):
    return u if isinstance(u, str) and u.startswith("https://") else ""


def stamp(first_seen, now):
    fs = loc(first_seen)
    new = (now - fs) <= timedelta(hours=NEW_H)
    label = f"Lagt ind {fs.day}. {MON[fs.month - 1]} kl. {fs:%H:%M}"
    if new:
        return f'<span class="stamp new" data-added="{fs:%Y-%m-%dT%H:%M}"><b>Nyt</b> {label}</span>'
    return f'<span class="stamp" data-added="{fs:%Y-%m-%dT%H:%M}">{label}</span>'


def collect(feeds, seen, now):
    items, by_link = [], {}
    bootstrap = not seen          # første kørsel: brug kildens tid som "lagt ind", så ikke alt står som Nyt
    for f in feeds.get("feeds", []):
        if f.get("status") != "ok":
            continue
        for it in f.get("items", []):
            link = safe_url(it.get("link"))
            title = (it.get("title") or "").strip()
            if not link or not title:
                continue
            pub = parse_dt(it.get("published"))
            if link not in seen:
                first = pub if (bootstrap and pub and pub < now) else now
                seen[link] = first.astimezone(timezone.utc).isoformat(timespec="minutes")
            rec = {"source": f.get("source", ""), "fname": f.get("name", ""), "topic": f.get("topic", ""),
                   "title": title, "link": link, "pub": pub, "summary": (it.get("summary") or "").strip(),
                   "first": parse_dt(seen[link]) or now}
            if link in by_link:       # samme artikel i flere DR-feeds: behold første
                continue
            by_link[link] = rec
            items.append(rec)
    return items


def label(src):
    return SOURCE_LABEL.get(src, src)


def item_html(r, now):
    en = r["source"] in EN_SOURCES
    rumor = r["source"] in RUMOR_SOURCES
    lang = ' lang="en"' if en else ""
    parts = [f'<article class="item" data-pub="{iso_local(r["pub"])}"><h3{lang}>{E(r["title"])}</h3>', stamp(r["first"], now)]
    if r["summary"]:
        tag = '<span class="tag rygte">Rygte</span>' if rumor else '<span class="tag fakta">Fra kilden</span>'
        parts.append(f'<p>{tag} <span{lang}>{E(r["summary"])}</span></p>')
    elif rumor:
        parts.append('<p><span class="tag rygte">Rygte</span> Rygteside. Ikke bekræftet af producenten.</p>')
    extra = " (engelsk)" if en else ""
    extra += " · rygteside" if rumor else ""
    parts.append(f'<p class="src">Kilde: {E(label(r["source"]))}{extra} · {pubtxt(r["pub"], now)}</p>')
    parts.append(f'<p class="more"><span>Læs mere:</span> <a href="{E(r["link"])}" target="_blank" rel="noopener">'
                 f'{E(label(r["source"]))} ↗</a></p></article>')
    return "".join(parts)


def segments(items, now):
    cutoff = now - timedelta(hours=MAX_AGE_H)
    seg = {k: [] for k in CAPS}
    for r in sorted((r for r in items if r["pub"] and r["pub"] >= cutoff), key=lambda r: r["pub"], reverse=True):
        text = r["title"] + " " + r["summary"]
        t = r["topic"]
        if t in ("teknologi", "ai", "foto"):
            seg[t].append(r)
        elif t == "outdoor":
            if not RE_NOHUNT.search(text):
                seg["outdoor"].append(r)
        elif t in ("alment", "danmark"):
            if RE_INDV.search(text):
                seg["indvandring"].append(r)
            elif RE_DAGP.search(text):
                seg["dagpenge"].append(r)
            elif t == "danmark" or (r["source"] == "DR" and r["fname"] in ("Indland", "Politik", "Penge")):
                seg["danmark"].append(r)
    for k in seg:
        seen_t, out = set(), []
        for r in seg[k]:
            nt = norm_title(r["title"])
            if nt in seen_t:
                continue
            seen_t.add(nt)
            out.append(r)
        seg[k] = out[:CAPS[k]]
    return seg


def latest_html(items, now):
    rows, seen_t, per_src = [], set(), {}
    for r in sorted((r for r in items if r["pub"]), key=lambda r: r["pub"], reverse=True):
        nt = norm_title(r["title"])
        if nt in seen_t or per_src.get(r["source"], 0) >= 5:
            continue
        seen_t.add(nt)
        per_src[r["source"]] = per_src.get(r["source"], 0) + 1
        lab = label(r["source"]) + (" · Rygte" if r["source"] in RUMOR_SOURCES else "")
        en = r["source"] in EN_SOURCES
        rows.append(f'<li data-pub="{iso_local(r["pub"])}"><span class="lt-t">{E(lab)}</span>'
                    f'<span class="lt-h"{" lang=\"en\"" if en else ""}><a href="{E(r["link"])}" target="_blank" rel="noopener">{E(r["title"])}</a></span>'
                    f'<span class="lt-m">{stamp(r["first"], now)} {E(label(r["source"]))}, {pubtxt(r["pub"], now)}{", engelsk" if en else ""}</span></li>')
        if len(rows) >= 20:
            break
    rows.append('<li class="lt-dr"><span class="lt-t">Link</span><span class="lt-h"><a href="https://www.dr.dk/" target="_blank" '
                'rel="noopener">DR: Nyheder - Breaking - TV - Radio ↗</a></span><span class="lt-m">Åbner dr.dk</span></li>')
    return "".join(rows)


def metro_section(m):
    if m.get("status") != "ok":
        return [f'<li><b>Nu</b>Metroens side kunne ikke læses ({E(str(m.get("status", "ingen data")))}). '
                f'<a href="https://m.dk/da/drift-og-service/status-og-planlagte-driftsaendringer/" target="_blank" rel="noopener">m.dk ↗</a></li>']
    li = [f'<li><b>Nu</b>{E(m.get("now") or "")}</li>']
    for e in m.get("elevators", []):
        li.append(f'<li><b>Elevator</b>{E(e.get("station", ""))}: {E(e.get("text", ""))}</li>')
    li.append('<li><b>Planlagt</b>Se planlagte ændringer på <a href="https://m.dk/da/drift-og-service/status-og-planlagte-driftsaendringer/" '
              'target="_blank" rel="noopener">m.dk ↗</a> (listen kan ikke læses automatisk).</li>')
    if m.get("stale_since"):
        li.append(f'<li><b>Bemærk</b>Siden kunne ikke læses ved seneste hentning; viser data fra {E(m["stale_since"][11:16])} UTC.</li>')
    return li


def dsb_section(d):
    if d.get("status") != "ok":
        return [f'<li><b>Nu</b>DSB\'s side kunne ikke læses ({E(str(d.get("status", "ingen data")))}). '
                f'<a href="https://www.dsb.dk/trafikinformation/" target="_blank" rel="noopener">DSB ↗</a></li>']
    li = []
    for it in d.get("items", []):
        u = safe_url(it.get("url"))
        txt = E(it.get("title", ""))
        if it.get("route"):
            txt += f' ({E(it["route"])})'
        if it.get("updated"):
            txt += f'. {E(it["updated"])}'
        if u:
            txt += f'. <a href="{E(u)}" target="_blank" rel="noopener">Læs ↗</a>'
        li.append(f"<li><b>Akut</b>{txt}</li>")
    if not li:
        li.append('<li><b>Nu</b>Ingen akutte ændringer på DSB\'s side.</li>')
    li.append('<li><b>Planlagt</b><a href="https://www.dsb.dk/trafikinformation/planlagte-aendringer/" target="_blank" rel="noopener">'
              'Planlagte ændringer og sporarbejde ↗</a></li>')
    return li


def drift_block(extra, now):
    ex = extra or {}
    gen = parse_dt(ex.get("generated"))
    secs = [("Metro", metro_section(ex.get("metro", {}))),
            ("Tog (DSB)", dsb_section(ex.get("dsb", {}))),
            ("Bus", ['<li><b>Planlagt</b>Ændringer i busdriften vises kun på <a href="https://dinoffentligetransport.dk/planlaeg-din-rejse/'
                     'koereplaner-for-bus-og-havnebus/aendringer-i-bustrafikken" target="_blank" rel="noopener">Din Offentlige Transport ↗</a> '
                     '(siden kan ikke læses automatisk).</li>'])]
    body = "".join(f'<section class="ev-day"><h3>{E(h)}</h3><ul>{"".join(li)}</ul></section>' for h, li in secs)
    when = f"Hentet kl. {loc(gen):%H.%M}." if gen else "Hentetid ukendt."
    return ('<div class="ov-wx ov-tr"><h2>Drift · Offentlig transport</h2><div class="ev-scroll" tabindex="0" '
            f'aria-label="Driftsinformation for Metro, tog og bus">{body}</div><p class="src" {SRC_STYLE}>Scroll ned for flere. '
            f'Kilder: Metroen (m.dk), DSB Trafikinformation, Din Offentlige Transport. {when}</p></div>')


def events_block():
    return ('<div class="ov-ev"><h2>Mine events</h2><div class="ev-scroll" id="ev-box" tabindex="0" aria-label="Events de næste dage">'
            '<p class="ev-empty" style="margin:6px 0;font-size:.85rem;color:var(--muted)">Henter kalender …</p></div>'
            f'<p class="src" id="ev-src" {SRC_STYLE}>Kilde: dine egne kalendere.</p></div>')


def dagpenge_official(extra, now):
    ex = extra or {}
    rows = []
    for key, name in (("star", "STAR"), ("akasser", "A-kasser.dk")):
        d = ex.get(key, {})
        if d.get("status") != "ok":
            rows.append(f'<li><b>{name}:</b> kunne ikke læses ({E(str(d.get("status", "ingen data")))}).</li>')
            continue
        for it in d.get("items", [])[:3]:
            u = safe_url(it.get("url"))
            dt = it.get("date") or ""
            dtxt = ""
            if re.match(r"\d{4}-\d{2}-\d{2}", dt):
                y, mo, da = int(dt[:4]), int(dt[5:7]), int(dt[8:10])
                dtxt = f"{da}. {MON[mo - 1]}"
            link = f' <a href="{E(u)}" target="_blank" rel="noopener">↗</a>' if u else ""
            rows.append(f"<li><b>{dtxt}</b> {name}: {E(it.get('title', ''))}{link}</li>")
    return ('<div class="assess" id="dagpenge-officielt" style="font-style:normal"><p style="margin:0 0 6px"><span class="tag">Officielt</span> '
            '<b>Seneste fra STAR og A-kasser.dk</b></p><ul style="margin:0 0 8px;padding-left:18px">' + "".join(rows) +
            '</ul><p style="margin:0;font-size:.85rem">Hentes automatisk fra star.dk og a-kasser.dk. Listen skjules ikke af tidsfilteret.</p></div>')


def dmi_line(extra, now):
    d = (extra or {}).get("dmi", {})
    if d.get("status") != "ok":
        return ""
    t = None
    if d.get("time"):
        try:
            t = datetime.fromisoformat(d["time"]).replace(tzinfo=TZ)
        except Exception:
            t = None
    if not t or now - t > timedelta(hours=36):
        return ""
    u = safe_url(d.get("url"))
    lead = f" {E(d['lead'])}." if d.get("lead") else ""
    link = f' <a href="{E(u)}" target="_blank" rel="noopener">Læs ↗</a>' if u else ""
    return (f'<p class="wx-dmi" style="margin:6px 0 12px;font-size:.85rem;line-height:1.45"><b>DMI\'s meteorolog</b> '
            f'({t.day}. {MON[t.month - 1]} kl. {t:%H:%M}): {E(d.get("title", ""))}.{lead}{link}</p>')


RE_ALARM = re.compile(r"\bartikel ?[45]\b|\barticle ?[45]\b|terrortrusl|trusselsniveau|luftrum\w* (?:er )?lukket|lukker luftrum|"
                      r"kastrup\w*.{0,40}(?:lukket|lukker|evakuer)|lufthavn\w*.{0,30}lukket|strømafbrydelse|strømsvigt|blackout|"
                      r"evakuer|cyberangreb mod|angreb på (?:danmark|nato|et nato)|mobiliser|undtagelsestilstand|"
                      r"beredskab\w*.{0,30}(?:forhøj|akut|hæve)", re.I)


def threat_block(items, extra, now):
    """Automatisk trusselsfelt: alarmord i danske nyheder (24 t) + UM's rejsevejledning for Tyrkiet.
    Claudes tjek (tirsdag og fredag) lægges på i browseren fra databasen (settings/threat)."""
    base = load("threat_baseline.json", {}) or {}
    since = now - timedelta(hours=24)
    hits, seen_t = [], set()
    for r in sorted((r for r in items if r["pub"] and r["pub"] >= since and r["topic"] in ("alment", "danmark")),
                    key=lambda r: r["pub"], reverse=True):
        if RE_ALARM.search(r["title"] + " " + r["summary"]):
            nt = norm_title(r["title"])
            if nt not in seen_t:
                seen_t.add(nt)
                hits.append(r)
    um = (extra or {}).get("um_tyrkiet", {})
    state, parts = "ok", []
    if um.get("status") == "ok":
        lv = um.get("level")
        upd = (um.get("updated") or "").split(" Kl.")[0]
        if lv in ("orange", "rød"):
            state = "alert"
            parts.append(f'Tyrkiet: UM fraråder {"alle" if lv == "rød" else "ikke-nødvendige"} rejser til hele landet (opdateret {E(upd)}). '
                         f'<a href="{E(um["url"])}" target="_blank" rel="noopener">UM ↗</a>')
        elif um.get("updated") and um.get("updated") != base.get("um_tyrkiet_updated"):
            state = "watch"
            parts.append(f'UM har opdateret rejsevejledningen for Tyrkiet ({E(upd)}). '
                         f'<a href="{E(um["url"])}" target="_blank" rel="noopener">Tjek den ↗</a>')
        else:
            txt = {"gul": "Vær ekstra forsigtig", "grøn": "Vær opmærksom"}.get(lv, "niveau ukendt")
            parts.append(f"Tyrkiet: {txt} (UM, uændret siden {E(upd)}).")
    else:
        parts.append("Tyrkiet: UM's side kunne ikke læses.")
    if hits:
        if state == "ok":
            state = "watch"
        h = hits[0]
        more = f" (+{len(hits) - 1} mere)" if len(hits) > 1 else ""
        parts.insert(0, f'Mulig trigger i nyhederne, tjek selv: <a href="{E(h["link"])}" target="_blank" rel="noopener">{E(h["title"])}</a> '
                        f'({E(label(h["source"]))}, {pubtxt(h["pub"], now)}){more}.')
    else:
        parts.insert(0, "Ingen alarmord i de danske nyheder de seneste 24 timer.")
    return (f'<div class="threat" id="threat-strip" data-state="{state}" data-auto="{state}" role="status"><span class="threat-d" aria-hidden="true"></span>'
            f'<span class="threat-l">Trusselsbillede</span><span class="threat-s">{" ".join(parts)}</span>'
            f'<span class="threat-t">Automatisk kl. {now:%H:%M}</span></div>')


def db_scripts():
    return r'''<script id="cal-db">(function(){var box=document.getElementById('ev-box'),src=document.getElementById('ev-src'),miss=document.getElementById('cal-miss');if(!box)return;
var WD=['Søn.','Man.','Tirs.','Ons.','Tors.','Fre.','Lør.'],MN=['jan.','feb.','mar.','apr.','maj','jun.','jul.','aug.','sep.','okt.','nov.','dec.'];
function p2(n){return('0'+n).slice(-2);}function dkey(d){return d.getFullYear()+'-'+p2(d.getMonth()+1)+'-'+p2(d.getDate());}
function msg(t){box.textContent='';var p=document.createElement('p');p.className='ev-empty';p.style.cssText='margin:6px 0;font-size:.85rem;color:var(--muted)';p.textContent=t;box.appendChild(p);}
function when(u){return u.getDate()+'. '+MN[u.getMonth()]+' kl. '+p2(u.getHours())+'.'+p2(u.getMinutes());}
function render(v){var now=new Date(),today=dkey(now),days=(v&&Array.isArray(v.days))?v.days.slice():[],n=0;box.textContent='';
days.sort(function(a,b){return String(a&&a.date).localeCompare(String(b&&b.date));});
days.forEach(function(d){if(!d||typeof d.date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(d.date)||d.date<today)return;
var its=(Array.isArray(d.items)?d.items:[]).filter(function(it){if(!it||!it.title)return false;if(it.end){var e=Date.parse(it.end);if(!isNaN(e)&&e<now.getTime())return false;}return true;});if(!its.length)return;
var dt=new Date(d.date+'T12:00:00'),h=WD[dt.getDay()]+' '+dt.getDate()+'. '+MN[dt.getMonth()];if(d.date===today)h='I dag · '+h;
var sec=document.createElement('section');sec.className='ev-day';var h3=document.createElement('h3');h3.textContent=h;sec.appendChild(h3);var ul=document.createElement('ul');
its.forEach(function(it){var li=document.createElement('li'),b=document.createElement('b');b.textContent=String(it.t||'');li.appendChild(b);li.appendChild(document.createTextNode(String(it.title)));ul.appendChild(li);n++;});
sec.appendChild(ul);box.appendChild(sec);});
if(!n)msg('Ingen events de næste dage.');
var u=v&&v.updated?new Date(v.updated):null,ok=u&&!isNaN(u);
if(src)src.textContent='Dage uden events er skjult. Scroll ned for flere. Kilde: dine egne kalendere'+(ok?', hentet fra din telefon '+when(u):'')+'.';
if(miss)miss.textContent=ok?('Hentet fra din telefon '+when(u)+'. Opdater fra Claude-appen: skriv "opdater kalender".'):'Ikke hentet endnu. Skriv "opdater kalender" i Claude-appen på telefonen.';}
if(!window.claude||!claude.use){msg('Kalenderen kan kun vises i Claude.');return;}
claude.use('db').then(function(db){if(!db)throw 0;return db.doc('settings/calendar').get();}).then(function(x){if(x&&x.exists)render(x.data());else{msg('Ingen kalender hentet endnu. Skriv "opdater kalender" i Claude-appen.');if(miss)miss.textContent='Ikke hentet endnu. Skriv "opdater kalender" i Claude-appen på telefonen.';}}).catch(function(){msg('Kalenderen kunne ikke hentes lige nu.');});})();</script>
<script id="threat-db">(function(){var el=document.getElementById('threat-strip');if(!el||!window.claude||!claude.use)return;var s=el.querySelector('.threat-s'),t=el.querySelector('.threat-t'),MN=['jan.','feb.','mar.','apr.','maj','jun.','jul.','aug.','sep.','okt.','nov.','dec.'];
function p2(n){return('0'+n).slice(-2);}
claude.use('db').then(function(db){if(!db)throw 0;return db.doc('settings/threat').get();}).then(function(x){if(!x||!x.exists)return;
var v=x.data()||{},c=v.checked?new Date(v.checked):null;if(!c||isNaN(c)||Date.now()-c.getTime()>96*3600000)return;
var sp=document.createElement('span');sp.className='threat-c';sp.textContent=' Claudes tjek '+c.getDate()+'. '+MN[c.getMonth()]+' kl. '+p2(c.getHours())+':'+p2(c.getMinutes())+': '+String(v.text||'');s.appendChild(sp);
if(v.state==='alert')el.setAttribute('data-state','alert');else if(v.state==='pending'&&el.getAttribute('data-state')==='ok')el.setAttribute('data-state','watch');}).catch(function(){});})();</script>'''


def miss_html(feeds, extra, now, built):
    fl = feeds.get("feeds", []) if feeds else []
    ok = sum(1 for f in fl if f.get("status") == "ok")
    bad = [f"{label(f.get('source', ''))} {f.get('name', '')}: {f.get('status')}" for f in fl if f.get("status") != "ok"]
    fg = parse_dt(feeds.get("generated")) if feeds else None
    ftxt = f"RSS hentet kl. {loc(fg):%H:%M}" if fg else "RSS-tid ukendt"
    ex = extra or {}
    st = ", ".join(f"{n} {'ok' if ex.get(k, {}).get('status') == 'ok' else 'fejl'}" for k, n in
                   (("metro", "Metro"), ("dsb", "DSB"), ("star", "STAR"), ("akasser", "A-kasser.dk"), ("dmi", "DMI-kommentar"),
                    ("um_tyrkiet", "UM Tyrkiet")))
    p = [
        '<p><b>Kalender:</b> <span id="cal-miss">Mine events vises fra databasen. Opdater dem fra Claude-appen på telefonen: skriv "opdater kalender".</span></p>',
        '<p><b>Vejr:</b> Vejrdata mangler i denne opdatering.</p>',
        f'<p><b>Nyheder:</b> {ftxt} ({len(fl)} feeds, {ok} ok){". Fejl: " + E("; ".join(bad)) if bad else ""}. Overskrifter og korte resuméer kommer fra '
        'kildernes egne RSS-feeds. Ingen artikler er læst eller vurderet. Engelske overskrifter står på engelsk.</p>',
        f'<p><b>Drift og officielle kilder:</b> {E(st)}. Bus kan ikke læses automatisk.</p>',
        '<p><b>Filter:</b> Siden Indstillinger (tandhjul øverst) styrer, hvilke artikler forsiden viser (kategorier, maksimal alder, antal pr. kategori). '
        'Standard er 12 timer; Outdoor og Fotografi 3 døgn. »Seneste nyt«-bjælken følger ikke filteret. Artikler ældre end 7 dage kommer ikke med.</p>',
        f'<p><b>Opdatering:</b> Siden bygges automatisk af GitHub hvert 10. minut kl. 06–23. Claude lægger den op kl. ca. 06:50 og 16, og når du '
        f'trykker »Opdater nu«. Trusselsfeltet er automatisk (alarmord i nyhederne og UM\'s rejsevejledning for Tyrkiet); Claude tjekker desuden tirsdag og fredag. Denne udgave er bygget {built.day}. {MON[built.month - 1]} kl. {built:%H:%M}.</p>',
    ]
    return "\n  ".join(p)


def sources_html(feeds):
    seen, li = set(), []
    for f in (feeds or {}).get("feeds", []):
        u = safe_url(f.get("url"))
        key = f.get("source")
        if not u or key in seen:
            continue
        seen.add(key)
        li.append(f'<li><a href="{E(u)}" target="_blank" rel="noopener">{E(label(key))} (RSS)</a></li>')
    for name, u in (("Metroen", "https://m.dk/da/drift-og-service/status-og-planlagte-driftsaendringer/"),
                    ("DSB Trafikinformation", "https://www.dsb.dk/trafikinformation/"),
                    ("STAR", "https://www.star.dk/om-styrelsen/nyt/nyheder-og-aktuelt-fra-styrelsen-for-arbejdsmarked-og-rekruttering"),
                    ("A-kasser.dk", "https://www.a-kasser.dk/nyheder"), ("DMI", "https://www.dmi.dk/meteorologens-kommentar"),
                    ("met.no", "https://api.met.no/")):
        li.append(f'<li><a href="{E(u)}" target="_blank" rel="noopener">{E(name)}</a></li>')
    return "".join(li)


def main():
    now = datetime.now(TZ)
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    feeds = load("feeds.json", {"feeds": []})
    extra = load("extra.json", {})
    seen = load("seen.json", {})
    items = collect(feeds, seen, now)
    seg = segments(items, now)
    try:
        events_static = open(os.path.join(HERE, "outdoor_events.html"), encoding="utf-8").read().strip()
    except Exception:
        events_static = ""
    week = now.isocalendar()[1]
    rep = {
        "{{DATE}}": f"{WEEKDAY[now.weekday()]} {now.day}. {MONTH[now.month - 1]} {now.year} · Uge {week}",
        "{{UPDATED}}": f"{now.day}. {MONTH[now.month - 1]} {now.year} kl. {now:%H:%M}",
        "{{EVENTS}}": events_block(),
        "{{DRIFT}}": drift_block(extra, now),
        "{{DMI}}": dmi_line(extra, now),
        "{{THREAT}}": threat_block(items, extra, now),
        "{{LATEST}}": latest_html(items, now),
        "{{MISS}}": "  " + miss_html(feeds, extra, now, now),
        "{{SOURCES}}": sources_html(feeds),
        "{{COLOPHON_DATE}}": f"{WEEKDAY[now.weekday()]} {now.day}. {MONTH[now.month - 1]} {now.year}",
        "{{DB_SCRIPTS}}": db_scripts(),
    }
    for k in CAPS:
        body = "".join(item_html(r, now) for r in seg[k])
        if k == "dagpenge":
            body = dagpenge_official(extra, now) + body
        if k == "outdoor":
            body = events_static + body
        rep["{{SEC_" + k.upper() + "}}"] = body + FEMPTY
    page = tpl
    for k, v in rep.items():
        if page.count(k) != 1:
            raise SystemExit(f"Pladsholder {k} findes {page.count(k)} gange i template.html")
        page = page.replace(k, v)
    if "{{" in page:
        raise SystemExit("Ukendt pladsholder tilbage: " + re.search(r"\{\{[A-Z_]+\}\}", page).group(0))
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    # Vejr (vejr_html.py skriver vejrblokken, tidslinjen, radar og "Vejr:" i Redaktionen mangler)
    wx = {"ok": False}
    try:
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "vejr_html.py"), out, os.path.join(HERE, "weather.json")],
                           capture_output=True, text=True, timeout=60)
        try:
            wx = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"ok": False}
        except Exception:
            wx = {"ok": False, "fejl": r.stdout[-300:]}
        wx["exit"] = r.returncode
    except Exception as e:
        wx = {"ok": False, "fejl": f"{type(e).__name__}: {e}"}
    # Opryd seen.json (links set for mere end 10 dage siden)
    lim = now - timedelta(days=10)
    seen = {k: v for k, v in seen.items() if (parse_dt(v) or now) >= lim}
    with open(os.path.join(HERE, "seen.json"), "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=0, sort_keys=True)
    final = open(out, encoding="utf-8").read()
    info = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "built_local": now.strftime("%Y-%m-%d %H:%M"),
        "feeds_generated": feeds.get("generated"),
        "weather": {k: wx.get(k) for k in ("ok", "exit", "fejl", "celler", "hovedomraade", "radar") if k in wx},
        "counts": {k: len(v) for k, v in seg.items()},
        "latest": final.count('<li data-pub='),
        "bytes": len(final.encode("utf-8")),
        "checks": {
            "tl_li": len(re.findall(r'<li class="tl-c', final)),
            "one_body_end": final.count("</body></html>") == 1,
            "upd_script": final.count("trig_01Rut7s8SQXxyTnLeFweQRa3") == 1,
            "settings_sync": final.count('id="settings-sync"') == 1,
            "own_feeds": final.count('id="own-feeds"') == 1,
            "cal_db": final.count('id="cal-db"') == 1,
            "threat_db": final.count('id="threat-db"') == 1,
        },
    }
    with open(os.path.join(OUT_DIR, "build.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
