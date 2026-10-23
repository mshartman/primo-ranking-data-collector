# Collection and aggregation workflow

## 1. Prepare stable inputs

Create a fixed query CSV with unique query IDs. Record optional provenance such
as query source, intent category, variant group, expected identifier, and dataset
partition. Keep the same query file throughout a collection series unless the
change itself is documented as a new series.

Define each Primo tab and scope in `scope_profiles.json`. Give profiles neutral,
stable names such as `local`, `everything`, or `articles`.

## 2. Snapshot the active configuration

Before every run, update `configurations/current.json` with the active field,
date, resource-type, institution, and blending settings. Give the snapshot a
unique `config_id`. This is provenance only; the scripts do not edit Primo.

## 3. Collect the API results

Run `collect_queries.py` with the matching configuration ID. The collector:

1. validates the query file, profiles, configuration ID, depth, and page size;
2. requests each query/profile combination in pages of no more than 50 records;
3. retries rate-limit and server failures;
4. saves every raw response before flattening it;
5. writes record observations and query-level collection counts;
6. records request errors without exposing the API key;
7. refuses to overwrite an existing run directory.

Do not edit completed run folders. If a run must be repeated, collect a new run
with a new ID.

## 4. Transfer or archive runs

Transfer complete run directories, not individual CSV files. The raw pages,
manifest, query statistics, flattened results, and configuration snapshot form
one provenance unit.

When runs come from another operator, place each complete directory under the
same `runs` parent. The aggregator does not require the directories to have been
created on the same computer.

## 5. Aggregate the collection

Run `aggregate_runs.py` against the parent directory. It discovers directories
containing both `run_manifest.json` and `results.csv`, then creates:

- a run inventory;
- a combined query-observation table;
- a combined record-observation table;
- a distinct-record metadata index;
- a configuration JSONL file;
- an aggregate dataset manifest.

The aggregation is lossless with respect to the flattened result rows. Raw API
pages remain in their original run directories and are not duplicated.

## 6. Validate the handoff

Check `dataset_manifest.json` against the expected number of runs and record
observations. Verify that every intended `config_id` appears in `runs.csv` and
that failed request counts are understood before passing the aggregate dataset
to an analyst.

This repository ends at that handoff. Comparative statistics, relevance
judgments, prediction, visualization, and configuration recommendations belong
in a separate analysis project.

