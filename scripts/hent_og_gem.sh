#!/usr/bin/env bash
# Henter alle feeds og vejrdata og gemmer feeds.json og weather.json i main.
# Hvis en anden kørsel har gemt imens, hentes main igen, og de nye filer lægges ovenpå (op til 5 forsøg).
# Alt ligger i main(), så bash har læst hele scriptet, før "git reset" kan ændre filen.
set -euo pipefail

main() {
  git config user.name "rss-bot"
  git config user.email "rss-bot@users.noreply.github.com"

  python3 fetch_feeds.py
  python3 fetch_weather.py || echo "Vejrhentningen fejlede. feeds.json gemmes alligevel."
  cp feeds.json /tmp/feeds.json
  if [ -f weather.json ]; then cp weather.json /tmp/weather.json; fi

  local n
  for n in 1 2 3 4 5; do
    git fetch -q --depth=1 origin main
    git reset -q --hard origin/main
    cp /tmp/feeds.json feeds.json
    git add feeds.json
    if [ -f /tmp/weather.json ]; then cp /tmp/weather.json weather.json; git add weather.json; fi
    if git diff --cached --quiet; then
      echo "Ingen ændringer."
      return 0
    fi
    git commit -q -m "Opdater feeds og vejr"
    if git push -q origin HEAD:main; then
      echo "Gemt (forsøg $n)."
      return 0
    fi
    echo "Push afvist (forsøg $n). Prøver igen."
    sleep $((n * 5))
  done
  echo "Kunne ikke gemme efter 5 forsøg." >&2
  return 1
}

main "$@"; exit $?
