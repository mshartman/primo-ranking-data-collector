# Primo ranking data collector

This repository packages a repeatable process for collecting and aggregating
Primo VE search-result data. It does not evaluate ranking quality, recommend
settings, compare treatments, or include a prediction model.

The workflow has two jobs:

1. **Collection** — run a fixed query set through one or more Primo profiles and
   preserve immutable raw and flattened results with complete provenance.
2. **Aggregation** — consolidate any number of collected runs into consistent
   CSV and JSONL tables for later analysis in another tool.

No institution's credentials, identifiers, queries, catalog metadata, API
responses, scores, or configuration history are included.

## Requirements

- Python 3.10 or newer
- A Primo Search API key
- The view ID, tab codes, and scope codes to collect

```powershell
python -m pip install -r requirements.txt
```

## Local setup

Create local working files. These filenames are ignored by Git:

```powershell
Copy-Item queries.example.csv queries.csv
Copy-Item scope_profiles.example.json scope_profiles.json
Copy-Item configurations\configuration.example.json configurations\current.json

$env:PRIMO_API_KEY = "your-api-key"
$env:PRIMO_VID = "YOUR_INSTITUTION:YOUR_VIEW"
```

Replace the example queries and scope codes. Document the active Primo settings
in `configurations\current.json`. The configuration file is descriptive; the
collector does not alter Primo.

## Collect a run

The `config_id` inside the configuration JSON must match the command:

```powershell
python collect_queries.py `
  --config-id B0_BASELINE `
  --configuration configurations\current.json
```

By default, every query is collected from the profiles named `local` and
`everything` to a depth of 100. Select profiles explicitly when needed:

```powershell
python collect_queries.py `
  --config-id LOCAL_COLLECTION_01 `
  --configuration configurations\current.json `
  --profiles local
```

Each collection creates a new immutable directory:

```text
runs/
  B0_BASELINE_YYYYMMDDTHHMMSSZ/
    configuration.json
    query_stats.csv
    results.csv
    run_manifest.json
    raw/
      local/
      everything/
```

The run contains:

- untouched API responses for every page requested;
- one flattened row per returned record observation;
- one query summary row per profile and query;
- the configuration snapshot used to label the collection;
- timestamps, request counts, query-file hash, scope definitions, and errors.

The API key is never written to an output file.

## Aggregate collected runs

To combine every valid run under `runs`:

```powershell
python aggregate_runs.py `
  --runs-root runs `
  --output aggregates\all_runs_2026
```

To include only selected configuration IDs:

```powershell
python aggregate_runs.py `
  --runs-root runs `
  --config-ids B0_BASELINE TITLE_5 TITLE_10 `
  --output aggregates\selected_runs
```

The aggregate directory contains:

- `runs.csv` — one provenance row per collection run;
- `query_observations.csv` — query-level collection counts from every run;
- `record_observations.csv` — every flattened result row across all runs;
- `records.csv` — one metadata index row per distinct record key;
- `configurations.jsonl` — configuration snapshots linked to runs;
- `dataset_manifest.json` — table names, counts, included run IDs, and creation
  time.

Aggregation preserves scores and ranks as collected values but does not
calculate changes, effectiveness metrics, relevance measures, or predictions.

See [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) for table definitions and
[docs/WORKFLOW.md](docs/WORKFLOW.md) for the operating procedure.

## Repository contents

- `collect_queries.py` — paginated, immutable Primo API collection
- `aggregate_runs.py` — consolidation into portable tabular datasets
- `queries.example.csv` — synthetic query-file structure
- `scope_profiles.example.json` — placeholder Local and blended profiles
- `configurations/configuration.example.json` — configuration snapshot structure
- `docs/WORKFLOW.md` — collection and handoff procedure
- `docs/DATA_SCHEMA.md` — outputs and keys
- `docs/DATA_SAFETY.md` — credential and data handling
- `tests/` — synthetic fixtures only

## Test the package

```powershell
python -m unittest discover -s tests -v
```

