from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Any


def write_json(path: Path, payload: Mapping[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]], *, sort_keys: bool = True) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=sort_keys))
            handle.write("\n")
            count += 1
    return count


def write_parquet(
    path: Path, records: Iterable[Mapping[str, Any]], *, columns: Iterable[str] | None = None
) -> int:
    """Write records as a Parquet table and return the number of rows.

    ``pyarrow`` is intentionally imported lazily so callers get a clear runtime
    error when the formal Parquet dependency is missing.
    """

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised in dependency setup failures
        raise RuntimeError(
            "pyarrow is required to write foundation_data/ecc Parquet tables"
        ) from exc

    column_names = list(columns or [])
    rows = [
        {column: record.get(column) for column in column_names} if column_names else dict(record)
        for record in records
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if column_names and not rows:
        table = pa.Table.from_pylist(
            rows, schema=pa.schema([(column, pa.string()) for column in column_names])
        )
    else:
        table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)
    return len(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
