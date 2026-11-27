#!/usr/bin/env bash
# Henter feeds, vejr (og evt. radar) og gemmer filerne i main.
# Miljø:
#   PLACES_JSON  JSON-liste med områder fra Indstillinger (valgfri). Sætter locations.json først.
#   RADAR=1      Lav også radarbillede (kræver numpy, h5py, pillow, pyproj).
# Kun filer, som DENNE kørsel har lavet, gemmes. Hvis en anden kørsel har gemt imens,
# hentes main igen, og de nye filer lægges ovenpå (op til 5 forsøg).
# Feeds venter højst VEJR_VENT sekunder (standard 20) på vejret. Er vejret ikke færdigt,
# gemmes feeds (og radar) først, og vejret gemmes bagefter i et ekstra commit.
# Til sidst bygges hele siden (build_page.py -> site/index.html), som Claude-opgaven lægger op uændret.
# Alt ligger i main(), så bash har læst hele scriptet, før "git reset" i starten kan ændre filen.
set -euo pipefail

gem() {
  # gem "<filer>" "<besked>": lægger filerne fra /tmp/ud oven på nyeste main og pusher (op til 5 forsøg).
  # Det sker i en separat worktree (/tmp/gemrepo), så arbejdsmappen aldrig nulstilles,
  # mens vejr- eller radarhentningen stadig skriver filer.
  local files="$1" msg="$2" n f
  local W=/tmp/gemrepo
  if ! git -C "$W" rev-parse -q --verify HEAD >/dev/null 2>&1; then
    rm -rf "$W"; git worktree prune
    git worktree add -q --detach "$W" HEAD
  fi
  for n in 1 2 3 4 5; do
    git -C "$W" fetch -q --depth=1 origin main
    git -C "$W" reset -q --hard FETCH_HEAD
    for f in $files; do
      if [ -f "/tmp/ud/$f" ]; then mkdir -p "$W/$(dirname "$f")"; cp "/tmp/ud/$f" "$W/$f"; git -C "$W" add "$f"; fi
    done
    if git -C "$W" diff --cached --quiet; then
      echo "Ingen ændringer ($files)."
      return 0
    fi
    git -C "$W" -c user.name=rss-bot -c user.email=rss-bot@users.noreply.github.com commit -q -m "$msg"
    if git -C "$W" push -q origin HEAD:main; then
      echo "Gemt (forsøg $n): $files"
      return 0
    fi
    echo "Push afvist (forsøg $n). Prøver igen."
    sleep $((n * 5))
  done
  echo "Kunne ikke gemme efter 5 forsøg: $files" >&2
  return 1
}

byg() {
  # Bygger site/index.html. Fejler bygningen, gemmes de andre filer stadig.
  if python3 build_page.py > /tmp/build.log 2>&1; then
    echo "Side bygget: $(tail -c 400 /tmp/build.log)"
    return 0
  fi
  echo "Bygning af siden fejlede:"; cat /tmp/build.log || true
  return 1
}

kopier() {
  local f
  for f in $1; do
    if [ -f "$f" ]; then mkdir -p "/tmp/ud/$(dirname "$f")"; cp "$f" "/tmp/ud/$f"; fi
  done
}

main() {
  git config user.name "rss-bot"
  git config user.email "rss-bot@users.noreply.github.com"
  rm -rf /tmp/ud && mkdir -p /tmp/ud
  local files="feeds.json" f
  # Start fra nyeste main (fx nye områder i locations.json fra en anden kørsel)
  git fetch -q --depth=1 origin main && git reset -q --hard FETCH_HEAD || echo "Kunne ikke hente nyeste main; bruger den lokale kopi."

  if [ -n "${PLACES_JSON:-}" ]; then
    if python3 set_places.py "$PLACES_JSON"; then files="$files locations.json"; fi
  fi

  # Vejr, radar og ekstra kilder hentes samtidig med feeds, så de ikke forsinker nyhederne
  python3 fetch_weather.py > /tmp/vejr.log 2>&1 &
  local wpid=$!
  python3 fetch_extra.py > /tmp/extra.log 2>&1 &
  local xpid=$!
  local rpid=""
  if [ "${RADAR:-0}" = "1" ]; then
    python3 fetch_radar.py > /tmp/radar.log 2>&1 &
    rpid=$!
  fi
  python3 fetch_feeds.py

  # Vent højst VEJR_VENT sekunder på vejret (og radaren)
  local t=0 maxw="${VEJR_VENT:-20}"
  while [ "$t" -lt "$maxw" ]; do
    if ! kill -0 "$wpid" 2>/dev/null && ! kill -0 "$xpid" 2>/dev/null && { [ -z "$rpid" ] || ! kill -0 "$rpid" 2>/dev/null; }; then break; fi
    sleep 1; t=$((t + 1))
  done

  local late=""
  if kill -0 "$wpid" 2>/dev/null; then
    late="1"
    echo "Vejret er ikke færdigt efter ${maxw} s. Feeds gemmes først."
  else
    if wait "$wpid"; then files="$files weather.json"; else echo "Vejrhentningen fejlede."; fi
    cat /tmp/vejr.log || true
  fi
  if [ -n "$rpid" ] && ! kill -0 "$rpid" 2>/dev/null; then
    wait "$rpid" || echo "Radar fejlede."
    cat /tmp/radar.log || true
    if [ -f radar.json ]; then files="$files radar.json"; fi
    if [ -f radar.png ] && grep -q '"near"' radar.json 2>/dev/null; then files="$files radar.png"; fi
    rpid=""
  fi
  if [ -n "$xpid" ] && ! kill -0 "$xpid" 2>/dev/null; then
    wait "$xpid" || echo "Ekstra kilder fejlede."
    cat /tmp/extra.log || true
    xpid=""
  fi
  if [ -f extra.json ]; then files="$files extra.json"; fi
  if byg; then files="$files site/index.html site/build.json seen.json"; fi
  kopier "$files"
  gem "$files" "Opdater feeds, vejr og side"

  if [ -n "$late" ] || [ -n "$rpid" ] || [ -n "$xpid" ]; then
    local more=""
    if [ -n "$xpid" ]; then
      wait "$xpid" || echo "Ekstra kilder fejlede."
      cat /tmp/extra.log || true
      if [ -f extra.json ]; then more="$more extra.json"; fi
    fi
    if [ -n "$late" ]; then
      if wait "$wpid"; then more="weather.json"; else echo "Vejrhentningen fejlede."; fi
      cat /tmp/vejr.log || true
    fi
    if [ -n "$rpid" ]; then
      wait "$rpid" || echo "Radar fejlede."
      cat /tmp/radar.log || true
      if [ -f radar.json ]; then more="$more radar.json"; fi
      if [ -f radar.png ] && grep -q '"near"' radar.json 2>/dev/null; then more="$more radar.png"; fi
    fi
    if [ -n "$more" ]; then
      if byg; then more="$more site/index.html site/build.json seen.json"; fi
      kopier "$more"
      gem "$more" "Opdater vejr og side"
    fi
  fi
}

main "$@"; exit $?
