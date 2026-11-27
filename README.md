# dr-rss
RSS til Dagens oversigt.

`fetch_feeds.py` henter feeds (DR, Ekstra Bladet, BT og emnefeeds) og gemmer overskrift, link og tid i `feeds.json`. Ingen artikeltekst.

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
