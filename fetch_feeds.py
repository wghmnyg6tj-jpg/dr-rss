"""Henter RSS-feeds og gemmer overskrifter, links og tidspunkter i feeds.json.
Gemmer kun titel, link og tid. Ingen artikeltekst.
Ret listen FEEDS for at tilføje eller fjerne feeds."""
import json, sys, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

FEEDS = [
    ("DR", "Seneste nyt", "https://www.dr.dk/nyheder/service/feeds/senestenyt"),
    ("DR", "Alle nyheder", "https://www.dr.dk/nyheder/service/feeds/allenyheder"),
    ("DR", "Indland", "https://www.dr.dk/nyheder/service/feeds/indland"),
    ("DR", "Udland", "https://www.dr.dk/nyheder/service/feeds/udland"),
    ("DR", "Politik", "https://www.dr.dk/nyheder/service/feeds/politik"),
    ("DR", "Penge", "https://www.dr.dk/nyheder/service/feeds/penge"),
    ("Ekstra Bladet", "Seneste", "https://ekstrabladet.dk/rssfeed/all/"),
    ("Ekstra Bladet", "Nyheder", "https://ekstrabladet.dk/rssfeed/nyheder/"),
    ("BT", "Nyheder", "https://www.bt.dk/nyheder/seneste/rss"),
    ("BT", "Seneste", "https://www.bt.dk/bt/seneste/rss"),
]
FEEDS = [(a, b, c, "alment") for a, b, c in FEEDS]
# Emnefeeds: fjerde felt er emnet (teknologi, ai, outdoor, foto, dagpenge, indvandring).
# Ikke alle adresser er verificeret. Et feed med status != "ok" kan fjernes.
TOPIC_FEEDS = [
    ("PetaPixel", "Foto", "https://petapixel.com/feed/", "foto"),
    ("Fuji Rumors", "Foto", "https://www.fujirumors.com/feed/", "foto"),
    ("Fstoppers", "Foto", "https://fstoppers.com/feed", "foto"),
    ("Version2", "Teknologi", "https://www.version2.dk/rss", "teknologi"),
    ("Ingeniøren", "Teknologi", "https://ing.dk/rss/nyheder", "teknologi"),
    ("Ars Technica", "Teknologi", "https://feeds.arstechnica.com/arstechnica/index", "teknologi"),
    ("The Verge", "AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "ai"),
    ("TechCrunch", "AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "ai"),
    ("The Neuron", "AI", "https://www.theneuron.ai/feed", "ai"),
    ("GearJunkie", "Outdoor", "https://gearjunkie.com/feed", "outdoor"),
    ("SectionHiker", "Outdoor", "https://sectionhiker.com/feed/", "outdoor"),
    ("The Trek", "Outdoor", "https://thetrek.co/feed/", "outdoor"),
    ("Outside", "Outdoor", "https://www.outsideonline.com/feed/", "outdoor"),
    ("Backpacker", "Outdoor", "https://www.backpacker.com/feed/", "outdoor"),
    ("Copenhagen Post", "Danmark", "https://cphpost.dk/feed/", "danmark"),
]
MAX_PER_FEED = 15
UA = "dagens-oversigt-rss/1.0 (privat nyhedsoverblik; hentes hvert kvarter)"

def iso(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="minutes")
    except Exception:
        return None

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()

def parse(body):
    root = ET.fromstring(body)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        items.append({"title": title, "link": link, "published": iso(it.findtext("pubDate"))})
    if not items:
        ns = "{http://www.w3.org/2005/Atom}"
        for it in root.iter(ns + "entry"):
            title = (it.findtext(ns + "title") or "").strip()
            link = ""
            for l in it.findall(ns + "link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            when = it.findtext(ns + "published") or it.findtext(ns + "updated")
            pub = None
            if when:
                try:
                    dt = datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    pub = dt.astimezone(timezone.utc).isoformat(timespec="minutes")
                except Exception:
                    pub = None
            if title and link.startswith("https://"):
                items.append({"title": title, "link": link, "published": pub})
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    return items[:MAX_PER_FEED]

def main():
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "feeds": []}
    for source, name, url, topic in FEEDS + TOPIC_FEEDS:
        entry = {"source": source, "name": name, "topic": topic, "url": url, "status": "ok", "items": []}
        try:
            code, body = fetch(url)
            entry["items"] = parse(body)
            if not entry["items"]:
                entry["status"] = "tomt feed"
        except urllib.error.HTTPError as e:
            entry["status"] = f"HTTP {e.code}"
        except Exception as e:
            entry["status"] = f"fejl: {type(e).__name__}"
        print(f"{name}: {entry['status']} ({len(entry['items'])} punkter)")
        out["feeds"].append(entry)
    with open("feeds.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

if __name__ == "__main__":
    sys.exit(main())
