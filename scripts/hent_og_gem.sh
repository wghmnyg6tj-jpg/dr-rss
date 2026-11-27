#!/usr/bin/env bash
# Henter feeds, vejr (og evt. radar) og gemmer filerne i main.
# Miljø:
#   PLACES_JSON  JSON-liste med områder fra Indstillinger (valgfri). Sætter locations.json først.
#   RADAR=1      Lav også radarbillede (kræver numpy, h5py, pillow, pyproj).
# Kun filer, som DENNE kørsel har lavet, gemmes. Hvis en anden kørsel har gemt imens,
# hentes main igen, og de nye filer lægges ovenpå (op til 5 forsøg).
# Alt ligger i main(), så bash har læst hele scriptet, før "git reset" kan ændre filen.
set -euo pipefail

main() {
  git config user.name "rss-bot"
  git config user.email "rss-bot@users.noreply.github.com"
  rm -rf /tmp/ud && mkdir -p /tmp/ud
  local files="feeds.json"

  if [ -n "${PLACES_JSON:-}" ]; then
    if python3 set_places.py "$PLACES_JSON"; then files="$files locations.json"; fi
  fi

  # Vejr og radar hentes samtidig med feeds, så de ikke forsinker nyhederne
  python3 fetch_weather.py > /tmp/vejr.log 2>&1 &
  local wpid=$!
  local rpid=""
  if [ "${RADAR:-0}" = "1" ]; then
    python3 fetch_radar.py > /tmp/radar.log 2>&1 &
    rpid=$!
  fi
  python3 fetch_feeds.py
  if wait "$wpid"; then files="$files weather.json"; else echo "Vejrhentningen fejlede."; fi
  cat /tmp/vejr.log || true
  if [ -n "$rpid" ]; then
    wait "$rpid" || echo "Radar fejlede."
    cat /tmp/radar.log || true
    if [ -f radar.json ]; then files="$files radar.json"; fi
    if [ -f radar.png ] && grep -q '"near"' radar.json 2>/dev/null; then files="$files radar.png"; fi
  fi
  local f
  for f in $files; do
    if [ -f "$f" ]; then cp "$f" /tmp/ud/; fi
  done

  local n
  for n in 1 2 3 4 5; do
    git fetch -q --depth=1 origin main
    git reset -q --hard origin/main
    for f in $files; do
      if [ -f "/tmp/ud/$f" ]; then cp "/tmp/ud/$f" "$f"; git add "$f"; fi
    done
    if git diff --cached --quiet; then
      echo "Ingen ændringer."
      return 0
    fi
    git commit -q -m "Opdater feeds og vejr"
    if git push -q origin HEAD:main; then
      echo "Gemt (forsøg $n): $files"
      return 0
    fi
    echo "Push afvist (forsøg $n). Prøver igen."
    sleep $((n * 5))
  done
  echo "Kunne ikke gemme efter 5 forsøg." >&2
  return 1
}

main "$@"; exit $?
