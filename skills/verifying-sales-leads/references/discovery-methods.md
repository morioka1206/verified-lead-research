# Choosing a discovery method

Pick the discovery method from the confirmed market and buyer types before searching, and show it in the final campaign brief as `候補の集め方` with a one-line expectation. Discovery only finds leads; every method feeds the same crawl, evidence check and acceptance gate.

## Which method

| Market | Buyer type | Method |
|---|---|---|
| The client's web-search country (Claude Code: United States) | any | Client web search; add OpenStreetMap for storefronts |
| Any other country | Storefronts: butchers, restaurants, cafes, bakeries, shops, supermarkets | OpenStreetMap import (`import_osm.py`), free |
| Any other country | Companies rarely on maps: importers, wholesalers, brands, manufacturers, B2B services | Country-targeted search (`search_web.py`, needs a Brave Search API key); without a key, client search plus an explicit warning that results will be few |

Claude Code's built-in web search returns US results only. In other markets it mostly returns directories, review sites and booking platforms, not the businesses' own sites (a German pilot found 3 new official sites in 48 queries). Say this in the brief instead of promising a count.

## OpenStreetMap presets

`import_osm.py --preset <name>` expands to OSM tags; combine presets and `--tag key=value` freely. List-valued keys such as `cuisine` match one item of a list (`japanese;sushi` matches `cuisine=japanese`). Each candidate records `osm_matched_tags`.

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

Areas are ISO 3166-2 first-level subdivisions (`DE-BY`, `FR-IDF`, `US-CA`). The importer falls back to a public Overpass mirror when the main server refuses or times out. Rerun the same command with the same `--output` later to fill areas that timed out; existing results are kept and deduplicated.

## Process likely buyers first

When one buyer type accepts far more often than another, import each type to its own file and add them with a batch priority so likely buyers are checked first:

```text
<python> scripts/import_osm.py --preset steak-restaurant --area DE-BE ... --output runs/<run>/discovery-osm-steak.json
<python> scripts/import_osm.py --preset butcher --area DE-BE ... --output runs/<run>/discovery-osm-butcher.json
<python> scripts/manage_batches.py add-candidates --run-dir runs/<run> --input runs/<run>/discovery-osm-steak.json --priority 10
<python> scripts/manage_batches.py add-candidates --run-dir runs/<run> --input runs/<run>/discovery-osm-butcher.json
```

`next-batch` takes the highest priority first, then discovery order. Priority changes only the order of work, never acceptance. Base it on measured acceptance rates from the first batch, not guesses, and tell the user which types were deferred: if the run stops at its target, deferred types may never be checked.

In the German wagyu pilot, steakhouses were mostly accepted because their menus name steak cuts, while many butchers were held for review because their sites list only sausage and pork.
