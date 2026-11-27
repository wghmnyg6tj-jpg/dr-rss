#!/usr/bin/env bash
# Henter alle feeds og gemmer feeds.json i main.
# Hvis en anden kørsel har gemt imens, hentes main igen, og den nye fil lægges ovenpå (op til 5 forsøg).
# Alt ligger i main(), så bash har læst hele scriptet, før "git reset" kan ændre filen.
set -euo pipefail

main() {
  git config user.name "rss-bot"
  git config user.email "rss-bot@users.noreply.github.com"

  python3 fetch_feeds.py
  cp feeds.json /tmp/feeds.json

  local n
  for n in 1 2 3 4 5; do
    git fetch -q --depth=1 origin main
    git reset -q --hard origin/main
    cp /tmp/feeds.json feeds.json
    git add feeds.json
    if git diff --cached --quiet; then
      echo "Ingen ændringer i feeds.json."
      return 0
    fi
    git commit -q -m "Opdater feeds"
    if git push -q origin HEAD:main; then
      echo "feeds.json gemt (forsøg $n)."
      return 0
    fi
    echo "Push afvist (forsøg $n). Prøver igen."
    sleep $((n * 5))
  done
  echo "Kunne ikke gemme feeds.json efter 5 forsøg." >&2
  return 1
}

main "$@"; exit $?
