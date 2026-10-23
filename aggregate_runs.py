"""Aggregate immutable Primo run folders into analysis-ready tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RUN_FIELDS = [
    "run_id",
    "config_id",
    "started_at_utc",
    "completed_at_utc",
    "vid",
    "profiles",
    "depth",
    "page_size",
    "query_count",
    "queries_sha256",
    "request_count",
    "successful_requests",
    "failed_requests",
    "result_rows",
    "query_stat_rows",
    "results_sha256",
    "configuration_file",
    "source_run_directory",
]

RECORD_FIELDS = [
    "record_key",
    "record_id",
    "mms_id",
    "source_record_id",
    "context",
    "adaptor",
    "title",
    "creator",
    "resource_type",
    "publication_year",
    "language",
    "subjects",
    "toc",
    "additional_title",
    "isbn",
    "issn",
    "doi",
    "institution",
    "library",
    "source",
    "is_cdi",
    "is_dedup",
    "document_url",
    "first_observed_at_utc",
    "last_observed_at_utc",
    "observation_count",
    "run_count",
    "query_count",
    "profile_count",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config-ids",
        nargs="*",
        help="Optional config_id filter. Omit to aggregate every valid run.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: Iterable[str] = ()) -> None:
    fieldnames: list[str] = []
    for name in preferred:
        if name not in fieldnames:
            fieldnames.append(name)
    for row in rows:
        for name in row:
            if name not in fieldnames:
                fieldnames.append(name)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def discover_runs(runs_root: Path) -> list[Path]:
    if not runs_root.is_dir():
        raise ValueError(f"Runs directory not found: {runs_root}")
    return sorted(
        path
        for path in runs_root.iterdir()
        if path.is_dir()
        and (path / "run_manifest.json").is_file()
        and (path / "results.csv").is_file()
    )


def load_configuration(run_dir: Path) -> tuple[str, dict[str, Any] | None]:
    candidates = sorted(run_dir.glob("configuration*.json"))
    if not candidates:
        return "", None
    path = candidates[0]
    return path.name, json.loads(path.read_text(encoding="utf-8-sig"))


def aggregate(
    run_dirs: list[Path],
    output: Path,
    config_ids: set[str] | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    run_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []
    observation_rows: list[dict[str, Any]] = []
    configurations: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        manifest_path = run_dir / "run_manifest.json"
        results_path = run_dir / "results.csv"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        config_id = str(manifest.get("config_id") or "")
        if config_ids and config_id not in config_ids:
            continue
        run_id = str(manifest.get("run_id") or run_dir.name)
        results = read_csv(results_path)
        stats = read_csv(run_dir / "query_stats.csv")
        configuration_name, configuration = load_configuration(run_dir)

        run_rows.append(
            {
                "run_id": run_id,
                "config_id": config_id,
                "started_at_utc": manifest.get("started_at_utc"),
                "completed_at_utc": manifest.get("completed_at_utc"),
                "vid": manifest.get("vid"),
                "profiles": json.dumps(manifest.get("profiles") or {}, sort_keys=True),
                "depth": manifest.get("depth"),
                "page_size": manifest.get("page_size"),
                "query_count": manifest.get("query_count"),
                "queries_sha256": manifest.get("queries_sha256"),
                "request_count": manifest.get("request_count"),
                "successful_requests": manifest.get("successful_requests"),
                "failed_requests": manifest.get("failed_requests"),
                "result_rows": len(results),
                "query_stat_rows": len(stats),
                "results_sha256": sha256(results_path),
                "configuration_file": configuration_name,
                "source_run_directory": run_dir.name,
            }
        )

        for row in stats:
            query_rows.append(
                {
                    "run_id": run_id,
                    "config_id": config_id,
                    "source_run_directory": run_dir.name,
                    **row,
                }
            )

        for row in results:
            observation_rows.append(
                {
                    "source_run_directory": run_dir.name,
                    **row,
                    "run_id": row.get("run_id") or run_id,
                    "config_id": row.get("config_id") or config_id,
                }
            )

        configurations.append(
            {
                "run_id": run_id,
                "config_id": config_id,
                "source_run_directory": run_dir.name,
                "configuration_file": configuration_name,
                "configuration": configuration,
            }
        )

    if not run_rows:
        raise ValueError("No runs matched the requested filters")

    record_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observation_rows:
        record_key = str(row.get("record_key") or "")
        if record_key:
            record_groups[record_key].append(row)

    record_rows: list[dict[str, Any]] = []
    metadata_fields = RECORD_FIELDS[: RECORD_FIELDS.index("first_observed_at_utc")]
    for record_key, rows in sorted(record_groups.items()):
        ordered = sorted(rows, key=lambda row: str(row.get("captured_at_utc") or ""))
        latest = ordered[-1]
        captured = [
            str(row.get("captured_at_utc") or "")
            for row in ordered
            if row.get("captured_at_utc")
        ]
        record: dict[str, Any] = {name: latest.get(name, "") for name in metadata_fields}
        record["record_key"] = record_key
        record.update(
            {
                "first_observed_at_utc": min(captured) if captured else "",
                "last_observed_at_utc": max(captured) if captured else "",
                "observation_count": len(rows),
                "run_count": len({str(row.get("run_id") or "") for row in rows}),
                "query_count": len({str(row.get("query_id") or "") for row in rows}),
                "profile_count": len({str(row.get("profile") or "") for row in rows}),
            }
        )
        record_rows.append(record)

    write_csv(output / "runs.csv", run_rows, RUN_FIELDS)
    write_csv(output / "query_observations.csv", query_rows)
    write_csv(output / "record_observations.csv", observation_rows)
    write_csv(output / "records.csv", record_rows, RECORD_FIELDS)
    with (output / "configurations.jsonl").open("w", encoding="utf-8") as handle:
        for item in configurations:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    dataset_manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run_count": len(run_rows),
        "query_observation_count": len(query_rows),
        "record_observation_count": len(observation_rows),
        "distinct_record_count": len(record_rows),
        "run_ids": [row["run_id"] for row in run_rows],
        "config_ids": sorted({str(row["config_id"]) for row in run_rows}),
        "files": {
            "runs": "runs.csv",
            "queries": "query_observations.csv",
            "observations": "record_observations.csv",
            "records": "records.csv",
            "configurations": "configurations.jsonl",
        },
        "note": "Aggregation only. No comparative or relevance evaluation is performed.",
    }
    (output / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return dataset_manifest


def main() -> int:
    args = parse_args()
    selected = set(args.config_ids) if args.config_ids else None
    manifest = aggregate(discover_runs(args.runs_root), args.output, selected)
    print(
        f"Aggregated {manifest['source_run_count']} runs and "
        f"{manifest['record_observation_count']} record observations into {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

