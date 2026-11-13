# Choosing a discovery method

Pick the discovery method from the confirmed market and buyer types before searching, and show it in the final campaign brief as `候補の集め方`. Discovery only finds leads; every method feeds the same crawl, evidence check and acceptance gate.

## Which method

| Market | Buyer type | Method |
|---|---|---|
| A country the client's web search covers | any | Client web search; add OpenStreetMap for storefronts |
| Any other country | Storefronts: butchers, restaurants, cafes, bakeries, shops, supermarkets | OpenStreetMap import (`import_osm.py`), free |
| Any other country | Companies rarely on maps: importers, wholesalers, brands, manufacturers, B2B services | Country-targeted search (`search_web.py`, needs a Brave Search API key); without a key, client web search plus a warning in the brief that results will be few |

Built-in search may be geographically biased or restricted in a particular environment (platform notes are in the repository's `docs/`). A US-only availability message alone does not prove results are US-only. Test the target market with a few local-language queries and check whether official business sites come back or only directories, reviews and booking platforms. Record the environment, date and observed limitation. Directory-heavy results are a warning, not proof that the country is unsupported. If coverage is poor, disclose it rather than promising a count. Use Brave only with the user's authorization for external API use; client search and public directories remain available alternatives.

Directories, review sites, maps and booking platforms are never a company URL or evidence. Use them only to reach a link to the company's own site, and record only a URL that appears as a link in the results.

## OpenStreetMap presets

`import_osm.py --preset <name>` expands to OSM tags; combine presets and `--tag key=value` freely. `cuisine` is matched as one item of OSM's semicolon list (`japanese;sushi` matches `cuisine=japanese`). Each candidate records `osm_matched_tags`; a company already present from an earlier area or run keeps its first record.

| Preset | Tags |
|---|---|
| `butcher` | `shop=butcher` |
| `deli` | `shop=deli` |
| `department-store` | `shop=department_store` |
| `steak-restaurant` | `cuisine=steak_house`, `argentinian`, `brazilian`, `barbecue` |
| `japanese-restaurant` | `cuisine=japanese`, `teppanyaki` |
| `cafe` | `amenity=cafe` |
| `tea-coffee-shop` | `shop=tea`, `shop=coffee` |
| `bakery` | `shop=bakery`, `shop=pastry` |
| `supermarket` | `shop=supermarket` |

Areas are ISO 3166-2 first-level subdivisions (`DE-BY`, `FR-IDF`, `US-CA`), one Overpass request each. The importer falls back to a public Overpass mirror, after the normal pause, when the main server refuses or times out. Rerun the same command with the same `--output` to retry areas that failed: areas already fetched for the same tags are skipped (tracked in `<output>.areas.json`), and earlier results are kept.

These are shared public servers. Keep the default `--pause`, never run several imports at the same time, and run one preset group after another.

## Checking likely buyers first

`manage_batches.py add-candidates --priority N` batches higher numbers first, then discovery order. Priority changes only the order of work, never acceptance. Adding a file again with a higher `--priority` raises its companies that are still queued.

1. Import each buyer type to its own file and add them all without a priority, so the first batch is a mixed sample.
2. After the first batch, compare acceptance rates by type in `audit.json`.
3. If one type is clearly better, add its file again with `--priority 10`. Its queued companies move ahead.

You may set a priority up front only from a previous run in the same industry and market. Say so in the brief.

```text
<python> scripts/import_osm.py --preset steak-restaurant --area DE-BE ... --output runs/<run>/discovery-osm-steak.json
<python> scripts/import_osm.py --preset butcher --area DE-BE ... --output runs/<run>/discovery-osm-butcher.json
<python> scripts/manage_batches.py add-candidates --run-dir runs/<run> --input runs/<run>/discovery-osm-steak.json
<python> scripts/manage_batches.py add-candidates --run-dir runs/<run> --input runs/<run>/discovery-osm-butcher.json
# after batch 1 shows steakhouses accept far more often:
<python> scripts/manage_batches.py add-candidates --run-dir runs/<run> --input runs/<run>/discovery-osm-steak.json --priority 10
```

`summary.json` reports `queued_by_priority`. When the run ends, tell the user how many lower-priority candidates were never checked.

Example from a previous run (German wagyu buyers): steakhouses were mostly accepted because their menus name steak cuts, while many butchers were held for review because their sites list only sausage and pork.
