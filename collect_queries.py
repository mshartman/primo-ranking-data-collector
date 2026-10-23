"""Collect immutable multi-query Primo ranking runs.

Credentials are read only from environment variables. The collector saves raw
API pages, flattened results, query statistics, and a provenance manifest under
``runs/<run_id>``. Generated run data is intentionally excluded from Git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


PROJECT_DIR = Path(__file__).resolve().parent
API_URL = os.getenv(
    "PRIMO_API_URL",
    "https://api-na.hosted.exlibrisgroup.com/primo/v1/search",
)
ALLOWED_FIELDS = {
    "any",
    "title",
    "creator",
    "sub",
    "isbn",
    "issn",
    "toc",
    "lang",
    "addtitle",
    "usertag",
}
FIELD_ALIASES = {"subject": "sub", "author": "creator", "keyword": "any"}
ALLOWED_PRECISIONS = {"contains", "exact", "begins_with"}

RESULT_FIELDS = [
    "run_id",
    "config_id",
    "captured_at_utc",
    "profile",
    "tab",
    "search_scope",
    "query_id",
    "query",
    "raw_query",
    "query_source",
    "query_intent",
    "variant_group",
    "query_field",
    "precision",
    "test_focus",
    "expected_record_id",
    "dataset_partition",
    "query_notes",
    "rank",
    "offset",
    "page_rank",
    "score",
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
]

QUERY_STAT_FIELDS = [
    "profile",
    "query_id",
    "query",
    "requested_depth",
    "returned",
    "total",
    "total_local",
    "total_central",
    "local_in_window",
    "central_in_window",
    "other_context_in_window",
    "pages_requested",
    "pages_succeeded",
    "pages_failed",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect an immutable multi-query Primo ranking run."
    )
    parser.add_argument("--config-id", required=True, help="Example: B0 or T_TITLE_4_5")
    parser.add_argument("--queries", type=Path, default=PROJECT_DIR / "queries.csv")
    parser.add_argument(
        "--scope-profiles",
        type=Path,
        default=PROJECT_DIR / "scope_profiles.json",
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=["local", "everything"],
        help="Profile names defined in scope_profiles.json",
    )
    parser.add_argument("--configuration", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_DIR / "runs")
    parser.add_argument("--run-id", help="Optional fixed run directory name")
    parser.add_argument("--depth", type=int, default=100)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--vid", default=os.getenv("PRIMO_VID", ""))
    return parser.parse_args()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "item"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def first(section: dict[str, Any], *keys: str) -> str:
    for key in keys:
        values = as_list(section.get(key))
        if values and values[0] is not None:
            return str(values[0])
    return ""


def joined(section: dict[str, Any], *keys: str) -> str:
    for key in keys:
        values = [str(item) for item in as_list(section.get(key)) if item is not None]
        if values:
            return " | ".join(values)
    return ""


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_api_key() -> str:
    environment_key = os.getenv("PRIMO_API_KEY", "").strip()
    if environment_key:
        return environment_key
    raise RuntimeError("Set the PRIMO_API_KEY environment variable before running.")


def load_scope_profiles(path: Path, selected: list[str]) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    profiles = data.get("profiles") or data
    missing = [name for name in selected if name not in profiles]
    if missing:
        raise ValueError(f"Unknown scope profiles: {', '.join(missing)}")
    result = {}
    for name in selected:
        profile = profiles[name]
        if not profile.get("tab") or not profile.get("scope"):
            raise ValueError(f"Profile {name} must define tab and scope")
        result[name] = {
            "tab": str(profile["tab"]),
            "scope": str(profile["scope"]),
            "description": str(profile.get("description") or ""),
        }
    return result


def load_queries(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No queries found in {path}")
    required = {"query_id", "query"}
    if not required.issubset(rows[0]):
        raise ValueError(f"{path} must contain query_id and query columns")

    output = []
    seen = set()
    for line_number, row in enumerate(rows, start=2):
        query_id = (row.get("query_id") or "").strip()
        query = (row.get("query") or "").strip()
        field = (row.get("field") or "any").strip().lower() or "any"
        field = FIELD_ALIASES.get(field, field)
        precision = (row.get("precision") or "contains").strip() or "contains"
        if not query_id or not query:
            raise ValueError(f"Missing query_id or query on line {line_number}")
        if query_id in seen:
            raise ValueError(f"Duplicate query_id: {query_id}")
        if field not in ALLOWED_FIELDS:
            raise ValueError(f"Unsupported field {field!r} for {query_id}")
        if precision not in ALLOWED_PRECISIONS:
            raise ValueError(f"Unsupported precision {precision!r} for {query_id}")
        if ";" in query:
            raise ValueError(f"Query {query_id} contains a semicolon, which Primo disallows")
        seen.add(query_id)
        query_intent = (
            row.get("query_intent") or row.get("test_focus") or ""
        ).strip()
        output.append(
            {
                "query_id": query_id,
                "query": query,
                "raw_query": (row.get("raw_query") or "").strip(),
                "query_source": (row.get("query_source") or "").strip(),
                "query_intent": query_intent,
                "variant_group": (row.get("variant_group") or "").strip(),
                "field": field,
                "precision": precision,
                "test_focus": query_intent,
                "expected_record_id": (row.get("expected_record_id") or "").strip(),
                "dataset_partition": (row.get("dataset_partition") or "development").strip(),
                "notes": (row.get("notes") or "").strip(),
            }
        )
    return output


def query_parameter(row: dict[str, str]) -> str:
    value = row["query"].replace(",", " ")
    return f"{row['field']},{row['precision']},{value}"


def validate_configuration(path: Path | None, config_id: str) -> None:
    if path is None:
        return
    if not path.is_file():
        raise ValueError(f"Configuration snapshot not found: {path}")
    if path.suffix.lower() != ".json":
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    documented_id = str(data.get("config_id") or "").strip()
    if not documented_id:
        raise ValueError(f"Configuration snapshot has no config_id: {path}")
    if documented_id != config_id:
        raise ValueError(
            f"Configuration config_id is {documented_id!r}, but --config-id is "
            f"{config_id!r}. Make them match before collecting."
        )


def describe_error(error: Exception) -> str:
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else "unknown"
        return f"HTTP status {status}"
    if isinstance(error, requests.Timeout):
        return "request timed out"
    if isinstance(error, requests.ConnectionError):
        return "connection failed"
    if isinstance(error, requests.RequestException):
        return f"request failed ({type(error).__name__})"
    return f"invalid JSON ({type(error).__name__})"


def fetch_page(
    session: requests.Session,
    *,
    api_url: str,
    api_key: str,
    params: dict[str, Any],
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(api_url, params={**params, "apikey": api_key}, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries:
                    time.sleep(2**attempt)
                    continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            last_error = error
            retryable = isinstance(
                error, (requests.Timeout, requests.ConnectionError)
            ) or (
                isinstance(error, requests.HTTPError)
                and error.response is not None
                and (error.response.status_code == 429 or error.response.status_code >= 500)
            )
            if retryable and attempt < retries:
                time.sleep(2**attempt)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Request failed without an error")


def flatten_doc(
    doc: dict[str, Any],
    *,
    run_id: str,
    config_id: str,
    captured_at: str,
    profile_name: str,
    profile: dict[str, str],
    query: dict[str, str],
    rank: int,
    offset: int,
    page_rank: int,
) -> dict[str, Any]:
    pnx = doc.get("pnx") or {}
    display = pnx.get("display") or {}
    control = pnx.get("control") or {}
    search = pnx.get("search") or {}
    sort = pnx.get("sort") or {}
    addata = pnx.get("addata") or {}
    facets = pnx.get("facets") or {}

    record_id = first(control, "recordid", "sourcerecordid")
    context = str(doc.get("context") or "")
    document_url = str(doc.get("@id") or "")
    record_key = f"{context}:{record_id}" if record_id else document_url

    return {
        "run_id": run_id,
        "config_id": config_id,
        "captured_at_utc": captured_at,
        "profile": profile_name,
        "tab": profile["tab"],
        "search_scope": profile["scope"],
        "query_id": query["query_id"],
        "query": query["query"],
        "raw_query": query["raw_query"],
        "query_source": query["query_source"],
        "query_intent": query["query_intent"],
        "variant_group": query["variant_group"],
        "query_field": query["field"],
        "precision": query["precision"],
        "test_focus": query["test_focus"],
        "expected_record_id": query["expected_record_id"],
        "dataset_partition": query["dataset_partition"],
        "query_notes": query["notes"],
        "rank": rank,
        "offset": offset,
        "page_rank": page_rank,
        "score": as_float(first(control, "score")),
        "record_key": record_key,
        "record_id": record_id,
        "mms_id": first(display, "mms") or first(addata, "mms"),
        "source_record_id": first(control, "sourcerecordid"),
        "context": context,
        "adaptor": str(doc.get("adaptor") or ""),
        "title": first(display, "title") or first(search, "title"),
        "creator": first(display, "creator") or first(sort, "author") or first(search, "creator"),
        "resource_type": first(display, "type") or first(control, "recordtype"),
        "publication_year": first(sort, "creationdate") or first(addata, "date"),
        "language": joined(display, "language") or joined(facets, "language"),
        "subjects": joined(display, "subject") or joined(search, "subject"),
        "toc": joined(search, "toc") or joined(display, "toc"),
        "additional_title": joined(search, "addtitle") or joined(display, "addtitle"),
        "isbn": joined(addata, "isbn"),
        "issn": joined(addata, "issn"),
        "doi": joined(addata, "doi"),
        "institution": joined(display, "institution", "availinstitution")
        or joined(facets, "institution"),
        "library": joined(facets, "library") or joined(display, "library"),
        "source": joined(display, "source") or first(control, "sourceid"),
        "is_cdi": first(control, "iscdi"),
        "is_dedup": first(control, "isDedup"),
        "document_url": document_url,
    }


def main() -> int:
    args = parse_args()
    if not 1 <= args.page_size <= 50:
        raise ValueError("--page-size must be between 1 and 50")
    if not 1 <= args.depth <= 5000:
        raise ValueError("--depth must be between 1 and 5000")
    if args.retries < 0:
        raise ValueError("--retries cannot be negative")
    if not args.vid.strip():
        print(
            "Set PRIMO_VID or provide --vid before running.",
            file=sys.stderr,
        )
        return 2

    try:
        validate_configuration(args.configuration, args.config_id)
        api_key = read_api_key()
        queries = load_queries(args.queries)
        profiles = load_scope_profiles(args.scope_profiles, args.profiles)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    run_id = args.run_id or f"{safe_name(args.config_id)}_{started:%Y%m%dT%H%M%SZ}"
    run_dir = args.output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    raw_dir = run_dir / "raw"
    raw_dir.mkdir()
    for profile_name in profiles:
        (raw_dir / safe_name(profile_name)).mkdir()

    copied_configuration = None
    if args.configuration:
        copied_configuration = run_dir / f"configuration{args.configuration.suffix}"
        shutil.copy2(args.configuration, copied_configuration)

    manifest: dict[str, Any] = {
        "collector_version": "1.0",
        "run_id": run_id,
        "config_id": args.config_id,
        "started_at_utc": started.isoformat(),
        "completed_at_utc": None,
        "api_url": args.api_url,
        "vid": args.vid,
        "profiles": profiles,
        "depth": args.depth,
        "page_size": args.page_size,
        "sort": "rank",
        "skip_delivery": True,
        "language": "en",
        "queries_file": str(args.queries.resolve()),
        "queries_sha256": sha256(args.queries),
        "query_count": len(queries),
        "configuration_file": str(copied_configuration) if copied_configuration else None,
        "request_count": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "errors": [],
        "security_note": "API key intentionally omitted from all output files.",
    }

    stats: list[dict[str, Any]] = []
    results_path = run_dir / "results.csv"
    session = requests.Session()
    try:
        with results_path.open("w", encoding="utf-8", newline="") as results_handle:
            writer = csv.DictWriter(results_handle, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            total_work = len(profiles) * len(queries)
            work_number = 0

            for profile_name, profile in profiles.items():
                for query in queries:
                    work_number += 1
                    print(
                        f"[{work_number}/{total_work}] {profile_name} / "
                        f"{query['query_id']}: {query['query']}"
                    )
                    query_stat = {
                        "profile": profile_name,
                        "query_id": query["query_id"],
                        "query": query["query"],
                        "requested_depth": args.depth,
                        "returned": 0,
                        "total": None,
                        "total_local": None,
                        "total_central": None,
                        "local_in_window": 0,
                        "central_in_window": 0,
                        "other_context_in_window": 0,
                        "pages_requested": 0,
                        "pages_succeeded": 0,
                        "pages_failed": 0,
                    }

                    for offset in range(0, args.depth, args.page_size):
                        limit = min(args.page_size, args.depth - offset)
                        query_stat["pages_requested"] += 1
                        manifest["request_count"] += 1
                        params = {
                            "vid": args.vid,
                            "tab": profile["tab"],
                            "scope": profile["scope"],
                            "q": query_parameter(query),
                            "sort": "rank",
                            "limit": limit,
                            "offset": offset,
                            "skipDelivery": "true",
                            "lang": "en",
                        }
                        captured_at = datetime.now(timezone.utc).isoformat()
                        try:
                            data = fetch_page(
                                session,
                                api_url=args.api_url,
                                api_key=api_key,
                                params=params,
                                timeout=args.timeout,
                                retries=args.retries,
                            )
                            manifest["successful_requests"] += 1
                            query_stat["pages_succeeded"] += 1
                        except (requests.RequestException, ValueError) as error:
                            safe_error = describe_error(error)
                            manifest["failed_requests"] += 1
                            query_stat["pages_failed"] += 1
                            manifest["errors"].append(
                                {
                                    "profile": profile_name,
                                    "query_id": query["query_id"],
                                    "offset": offset,
                                    "error": safe_error,
                                }
                            )
                            print(f"  Offset {offset} failed: {safe_error}", file=sys.stderr)
                            continue

                        raw_path = (
                            raw_dir
                            / safe_name(profile_name)
                            / f"{safe_name(query['query_id'])}_offset_{offset:04d}.json"
                        )
                        raw_path.write_text(
                            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        info = data.get("info") or {}
                        if query_stat["total"] is None:
                            query_stat["total"] = info.get("total")
                            query_stat["total_local"] = info.get("totalResultsLocal")
                            query_stat["total_central"] = info.get("totalResultsPC")

                        docs = data.get("docs") or []
                        for page_rank, doc in enumerate(docs, start=1):
                            row = flatten_doc(
                                doc,
                                run_id=run_id,
                                config_id=args.config_id,
                                captured_at=captured_at,
                                profile_name=profile_name,
                                profile=profile,
                                query=query,
                                rank=offset + page_rank,
                                offset=offset,
                                page_rank=page_rank,
                            )
                            writer.writerow(row)
                            query_stat["returned"] += 1
                            if row["context"] == "L":
                                query_stat["local_in_window"] += 1
                            elif row["context"] == "PC":
                                query_stat["central_in_window"] += 1
                            else:
                                query_stat["other_context_in_window"] += 1

                        if len(docs) < limit:
                            break
                        if args.delay > 0:
                            time.sleep(args.delay)
                    stats.append(query_stat)
    finally:
        session.close()
        manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (run_dir / "query_stats.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stats_handle:
            stats_writer = csv.DictWriter(stats_handle, fieldnames=QUERY_STAT_FIELDS)
            stats_writer.writeheader()
            stats_writer.writerows(stats)

    print(f"Saved run: {run_dir}")
    print(f"Results: {results_path}")
    return 1 if manifest["failed_requests"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
