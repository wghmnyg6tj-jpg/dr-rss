"""Tjekker, om den byggede side (site/build.json) er klar til at blive lagt op.

Brug:  python3 -I scripts/klar.py [T]
T = tidspunkt (ISO, UTC), som bygningen skal være nyere end, fx knaptrykket. Uden T: nu minus 15 minutter.
Exit 0 = ny og i orden. Exit 1 = i orden, men ikke nyere end T. Exit 2 = mangler eller fejl (læg ikke op).
"""
import json, os, sys
from datetime import datetime, timedelta, timezone

d = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse(s):
    try:
        x = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:
        return None


now = datetime.now(timezone.utc)
t = parse(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].strip() else None
t = t or now - timedelta(minutes=15)
try:
    b = json.load(open(os.path.join(d, "site", "build.json"), encoding="utf-8"))
    size = os.path.getsize(os.path.join(d, "site", "index.html"))
except Exception as e:
    print(json.dumps({"klar": False, "fejl": f"site/build.json eller site/index.html mangler ({type(e).__name__})"}, ensure_ascii=False))
    sys.exit(2)
gen = parse(b.get("generated", "")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
c = b.get("checks", {})
need = ["one_body_end", "upd_script", "settings_sync", "own_feeds", "cal_db", "threat_db"]
ok = all(c.get(k) for k in need) and size > 30000
res = {"klar": ok and gen > t, "i_orden": ok, "bygget_utc": b.get("generated"), "bygget_dansk": b.get("built_local"),
       "alder_min": round((now - gen).total_seconds() / 60, 1), "vejr_ok": (b.get("weather") or {}).get("ok"),
       "fil": os.path.join(d, "site", "index.html"), "bytes": size}
if not ok:
    res["fejl"] = "kontrol fejlede: " + ", ".join(k for k in need if not c.get(k))
print(json.dumps(res, ensure_ascii=False))
sys.exit(0 if res["klar"] else (1 if ok else 2))
