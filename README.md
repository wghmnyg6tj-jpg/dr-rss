# dr-rss
Bygger hele siden Dagens oversigt. Fra 27. nov. 2026 bygges siden her uden AI, så Claude kun lægger den færdige fil op (sparer forbrug).

## Hele kæden
1. GitHub henter feeds, vejr, radar og ekstra kilder hvert 10. minut kl. 06–23 (og ved "Opdater nu").
2. `build_page.py` bygger `site/index.html` ud fra `template.html` (design og scripts fra siden), `feeds.json`, `extra.json`, `weather.json`/`radar.*` (via `vejr_html.py`), `outdoor_events.html` og `seen.json`. `site/build.json` har tid og kontroller.
3. Claude-opgaverne (Haiku) kl. 7, 10, 13, 16 og "Opdater nu" kører `scripts/klar.py` og lægger `site/index.html` op uændret.
4. I browseren læser siden selv "Mine events" (`settings/calendar`) og trusselsfeltet (`settings/threat`) fra artifactens database. Kalenderen skrives fra Claude-appen ("opdater kalender"), trusselsfeltet af det daglige trusselstjek.

`fetch_extra.py` henter Metroens status og elevatorer (m.dk), DSB's akutte ændringer, STAR- og A-kasser.dk-nyheder og DMI's seneste meteorologkommentar til `extra.json`. Busændringer kan ikke læses automatisk.

Skabelonen: design, CSS og scripts ligger i `template.html` med pladsholdere som `{{SEC_DANMARK}}`. Ret designet der.

`fetch_feeds.py` henter feeds (DR, Ekstra Bladet, BT og emnefeeds) og gemmer overskrift, link, tid og kildens korte resumé (højst ca. 240 tegn) i `feeds.json`. Ingen artikeltekst.

`fetch_weather.py` henter vejr til `weather.json`: DMI HARMONIE-prognose for Mørkhøj, DMI-målinger (Jægersborg, Kastrup, Landbohøjskolen), DMI-lyn og met.no. `vejr_html.py` skriver vejret ind på Dagens oversigt ud fra `weather.json` og `radar.json`/`radar.png` (tidslinje med DMI-nedbør, temperatur nu, vejrtekst, ekstra områder, radar), så ingen tal skrives i hånden.

`set_places.py` sætter vejrområderne (`locations.json`) ud fra Indstillinger på siden. Workflowet "Hent RSS" får dem som input `places` (JSON-liste). Stednavne slås op hos OpenStreetMap Nominatim. Første område er hovedområdet.

`fetch_radar.py` laver `radar.png` (200 × 200 km omkring hovedområdet) ud fra DMI's radarkomposit. Kystlinjer: `dk_coast.json` (Natural Earth, public domain). Radar laves af den løbende hentning.

## Sådan kører det
- **Løbende (`rss-loop.yml`)**: henter hvert 10. minut kl. 06–23 dansk tid. Hver kørsel henter 6 gange (ca. 1 time) og starter selv den næste. Om natten stopper kæden.
- **Med det samme (`rss.yml`)**: én hentning nu. Startes af "Opdater nu" på Dagens oversigt (via den planlagte opgave "Start RSS-hentning før Dagens oversigt") og af de planlagte opgaver. Starter bagefter den løbende hentning, hvis den ikke kører.
- GitHubs egne planlagte kørsler (cron) er kun reserve. De starter sjældent.

## Læs filen
`https://raw.githubusercontent.com/wghmnyg6tj-jpg/dr-rss/main/feeds.json?t=<unix-tid>` (tallet bryder cachen).

## Stop eller start
- Stop helt: Actions → "Hent RSS løbende" → "…" → Disable workflow.
- Stop kun nu: annullér kørslen. Kæden starter igen næste gang `rss.yml` kører.
- Start: Actions → "Hent RSS" → Run workflow.
