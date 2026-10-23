# Aggregate data schema

## Identifiers

- `run_id` identifies one immutable API collection.
- `config_id` labels the documented Primo configuration active during that run.
- `query_id` is a stable identifier supplied in the query CSV.
- `profile` identifies the tab/scope pair used for the request.
- `record_key` combines source context and record identifier when available.

The natural key for a flattened observation is normally:

```text
run_id + profile + query_id + record_key
```

## `runs.csv`

One row per included run. It contains timestamps, source directory, view and
profile metadata, request counts, query count and hash, result-row count,
configuration filename, and the SHA-256 hash of `results.csv`.

## `query_observations.csv`

One row per run, profile, and query. It records requested depth, returned count,
reported total, Local/CDI counts within the collected window, and page success
or failure counts.

## `record_observations.csv`

Every row from every included `results.csv`, with the source run directory
attached. It preserves the collected score, rank, query metadata, record source,
and flattened bibliographic fields. No rows are averaged, deduplicated, or
compared.

## `records.csv`

One convenience row per distinct `record_key`. Metadata comes from the latest
observation in the aggregate. The table also reports first and last observation
times and counts of observations, runs, queries, and profiles. This is an index,
not an evaluation table.

## `configurations.jsonl`

One JSON object per run containing `run_id`, `config_id`, source directory,
configuration filename, and the complete parsed configuration snapshot. A null
configuration means the run directory did not contain a configuration JSON.

## `dataset_manifest.json`

Describes the aggregate creation time, included run and configuration IDs,
table filenames, and row counts. It explicitly states that the operation is
aggregation only.

