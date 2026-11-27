"""Henter ekstra kilder til Dagens oversigt og gemmer dem i extra.json.

Kilder (alle læses som almindelige websider; ingen login):
- Metroen (m.dk): status nu og elevatorer
- DSB Trafikinformation: akutte ændringer
- STAR: nyheder (dagpenge og beskæftigelse)
- A-kasser.dk: nyheder
- DMI: meteorologens seneste kommentar (overskrift, tid og første linje)
- Udenrigsministeriet: rejsevejledningen for Tyrkiet (niveau for hele landet og opdateringsdato)

PET (pet.dk) svarer ikke fra GitHub (timeout), så PET's trusselsniveau kan ikke hentes automatisk.

Bus (dinoffentligetransport.dk) indlæses med JavaScript og kan ikke læses her; siden linker til den.
Fejler en kilde, gemmes fejlen, og de andre kilder bruges stadig.
"""
import html
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 dagens-oversigt"
OUT = "extra.json"


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "da,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def text(x):
    x = re.sub(r"<svg[\s\S]*?</svg>", " ", x)
    x = re.sub(r"<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", html.unescape(x)).strip()


def metro():
    url = "https://m.dk/da/drift-og-service/status-og-planlagte-driftsaendringer/"
    s = get(url)
    m = re.search(r'<div class="track"><p>(.*?)</p>', s, re.S)
    status = text(m.group(1)) if m else ""
    elev = []
    for m in re.finditer(r'<div class="font-bold">([^<]+)</div>((?:\s*<div class="text-black-40">[^<]*</div>)+)', s):
        msg = " ".join(text(x) for x in re.findall(r'<div class="text-black-40">([^<]*)</div>', m.group(2)))
        st = text(m.group(1))
        if st and msg and not any(e["station"] == st and e["text"] == msg for e in elev):
            elev.append({"station": st, "text": msg})
    if not status:
        raise ValueError("status ikke fundet på siden")
    return {"url": url, "now": status, "elevators": elev[:8]}


def dsb():
    url = "https://www.dsb.dk/trafikinformation/"
    s = get(url)
    i = s.find(">Akutte ændringer</h2>")
    j = s.find("aria-label=\"Planlagte ændringer\"", i)
    seg = s[i:j if j > i else i + 20000] if i >= 0 else ""
    items = []
    for m in re.finditer(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', seg, re.S):
        href, inner = m.group(1), m.group(2)
        upd = re.search(r'<span[^>]*>((?:Opdateret|Seneste opdatering)[^<]*)</span>', inner)
        route = re.search(r'<h3[^>]*>(.*?)</h3>', inner, re.S)
        title = re.search(r'<p class="mt-4[^"]*"[^>]*>(.*?)</p>', inner, re.S)
        if not (route or title):
            continue
        items.append({
            "updated": text(upd.group(1)) if upd else "",
            "route": text(route.group(1)) if route else "",
            "title": text(title.group(1)) if title else "",
            "url": href if href.startswith("https://") else "https://www.dsb.dk" + href,
        })
    if i < 0:
        raise ValueError("afsnittet Akutte ændringer ikke fundet")
    return {"url": url, "items": items[:8]}


def star():
    url = "https://www.star.dk/om-styrelsen/nyt/nyheder-og-aktuelt-fra-styrelsen-for-arbejdsmarked-og-rekruttering"
    s = get(url)
    items = []
    for m in re.finditer(r'<li>\s*<a href="([^"]+)">(.*?)</a>\s*</li>', s, re.S):
        href, inner = m.group(1), m.group(2)
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", inner, re.S)
        if not h3 or "result-tags" not in inner:
            continue
        d = re.search(r"(\d{2})-(\d{2})-(\d{4})", inner)
        date = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None
        items.append({"date": date, "title": text(h3.group(1)), "url": href if href.startswith("https://") else "https://star.dk" + href})
    if not items:
        raise ValueError("ingen nyheder fundet")
    return {"url": url, "items": items[:8]}


def akasser():
    url = "https://www.a-kasser.dk/nyheder"
    s = get(url)
    i = s.find("Seneste nyheder om A-kasse")
    seg = s[i:] if i >= 0 else s
    items = []
    for m in re.finditer(r'<h3>(.*?)</h3>\s*<time datetime="([^"]+)">[^<]*</time>\s*<p>(.*?)</p>(?:\s*<p>(.*?)</p>)?', seg, re.S):
        title, dt, p1, p2 = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        link = re.search(r'href="([^"]+)"', p1 + p2)
        href = link.group(1) if link else ""
        if href and not href.startswith("http"):
            href = "https://www.a-kasser.dk" + (href if href.startswith("/") else "/" + href)
        summ = text(re.sub(r"<a [^>]*>.*?</a>", "", p1, flags=re.S))
        if len(summ) > 240:
            summ = summ[:240].rsplit(" ", 1)[0] + " …"
        items.append({"date": dt[:10], "title": text(title), "summary": summ, "url": href or url})
        if len(items) >= 6:
            break
    if not items:
        raise ValueError("ingen nyheder fundet")
    return {"url": url, "items": items}


def dmi():
    base = "https://www.dmi.dk"
    s = get(base + "/meteorologens-kommentar")
    m = re.search(r'href="(/meteorologens-kommentar/[^"#?]+)"[^>]*>\s*<span itemprop="headline">([^<]+)</span>', s)
    if not m:
        raise ValueError("seneste kommentar ikke fundet")
    url = base + m.group(1)
    d = get(url)
    title = re.search(r'<h1 itemprop="headline">(.*?)</h1>', d, re.S)
    when = re.search(r'datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})"', d)
    body = re.search(r'<div class="news-text-wrap" itemprop="articleBody">(.*?)</div>', d, re.S)
    lead = ""
    if body:
        st = re.search(r"<p><strong>(.*?)</strong></p>", body.group(1), re.S)
        lead = text(st.group(1)) if st else ""
    return {"url": url, "title": text(title.group(1)) if title else text(m.group(2)),
            "time": when.group(1) if when else None, "lead": lead[:200]}


def um_tyrkiet():
    url = "https://um.dk/rejse-og-ophold/rejse-til-udlandet/rejsevejledninger/tyrkiet"
    t = text(re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", get(url)))
    upd = re.search(r"Rejsevejledning opdateret:\s*([0-9.]+(?:\s*Kl\.\s*[0-9.]+)?)", t)
    i = t.find("Gyldig:")
    seg = t[i:i + 1500] if i >= 0 else t[:4000]
    level, line = None, ""
    for lv, pat in (("rød", r"Vi fraråder alle rejser:\s*Hele landet"),
                    ("orange", r"Vi fraråder alle ikke-nødvendige rejser:\s*Hele landet"),
                    ("gul", r"Vær ekstra forsigtig:\s*Hele landet"),
                    ("grøn", r"Vær opmærksom:\s*Hele landet")):
        m = re.search(pat, seg)
        if m:
            level = lv
            end = seg.find(".", m.start())
            line = seg[m.start(): end + 1 if end > 0 else m.start() + 160]
            break
    if not upd and not level:
        raise ValueError("rejsevejledningen kunne ikke læses")
    return {"url": url, "updated": upd.group(1).strip() if upd else None, "level": level, "line": line[:220]}


JOBS = {"metro": metro, "dsb": dsb, "star": star, "akasser": akasser, "dmi": dmi, "um_tyrkiet": um_tyrkiet}


def run(name):
    try:
        return name, {"status": "ok", **JOBS[name]()}
    except Exception as e:
        return name, {"status": f"fejl: {type(e).__name__}: {str(e)[:120]}"}


def main():
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, res in pool.map(run, JOBS):
            out[name] = res
            print(f"{name}: {res['status']}")
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {}
    # Fejler en kilde, beholdes den forrige udgave (markeret som gammel)
    for name in JOBS:
        if out[name]["status"] != "ok" and isinstance(prev.get(name), dict) and prev[name].get("status") == "ok":
            keep = dict(prev[name])
            keep["stale_since"] = prev.get("generated")
            keep["status_now"] = out[name]["status"]
            out[name] = keep
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)      # atomisk: build_page.py læser aldrig en halv fil
    return 0


if __name__ == "__main__":
    sys.exit(main())
