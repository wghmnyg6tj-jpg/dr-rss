#!/usr/bin/env bash
# Starter den løbende hentning (rss-loop.yml), hvis klokken er 06-23 dansk tid,
# og hvis der ikke allerede kører eller venter en anden kørsel af den.
# Kørslen, der kalder scriptet, tælles ikke med (GITHUB_RUN_ID).
set -euo pipefail

main() {
  local h
  h=$(TZ=Europe/Copenhagen date +%-H)
  if (( h < 6 || h >= 23 )); then
    echo "Nat (kl. $h dansk tid): starter ikke løbende hentning."
    return 0
  fi

  local andre
  andre=$(gh run list --repo "$GITHUB_REPOSITORY" --workflow rss-loop.yml --limit 20 \
    --json databaseId,status \
    --jq "[.[] | select(.databaseId != ${GITHUB_RUN_ID:-0}) | select(.status != \"completed\")] | length")
  if (( andre > 0 )); then
    echo "Løbende hentning kører eller venter allerede ($andre)."
    return 0
  fi

  gh workflow run rss-loop.yml --repo "$GITHUB_REPOSITORY" --ref main
  echo "Løbende hentning startet."
}

main "$@"; exit $?
