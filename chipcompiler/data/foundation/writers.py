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
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    columns: Iterable[str] | None = None,
    batch_size: int = 2048,
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

    column_names = tuple(columns or ())
    normalized_batch_size = max(1, int(batch_size))
    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    writer = None
    active_schema = None
    batch: list[dict[str, Any]] = []
    next_schema_check_size = normalized_batch_size

    def normalize(record: Mapping[str, Any]) -> dict[str, Any]:
        if column_names:
            return {column: record.get(column) for column in column_names}
        return dict(record)

    def flush(current_batch: list[dict[str, Any]]) -> None:
        nonlocal writer, row_count, active_schema
        if not current_batch:
            return
        table = pa.Table.from_pylist(current_batch, schema=active_schema)
        if writer is None:
            active_schema = table.schema
            writer = pq.ParquetWriter(path, table.schema)
        writer.write_table(table)
        row_count += len(current_batch)

    def has_null_typed_fields(rows: list[dict[str, Any]]) -> bool:
        if not rows:
            return False
        table = pa.Table.from_pylist(rows)
        return any(pa.types.is_null(field.type) for field in table.schema)

    def coerce_null_schema_rows(rows: list[dict[str, Any]]):
        inferred = pa.Table.from_pylist(rows)
        schema = pa.schema(
            [
                pa.field(field.name, pa.string()) if pa.types.is_null(field.type) else field
                for field in inferred.schema
            ]
        )
        return pa.Table.from_pylist(rows, schema=schema)

    try:
        for record in records:
            batch.append(normalize(record))
            if writer is None:
                if len(batch) < next_schema_check_size:
                    continue
                if has_null_typed_fields(batch):
                    next_schema_check_size += normalized_batch_size
                    continue
                flush(batch)
                batch = []
                next_schema_check_size = normalized_batch_size
            elif len(batch) >= normalized_batch_size:
                flush(batch)
                batch = []
        if writer is None:
            if batch:
                if has_null_typed_fields(batch):
                    table = coerce_null_schema_rows(batch)
                    active_schema = table.schema
                    writer = pq.ParquetWriter(path, table.schema)
                    writer.write_table(table)
                    row_count += len(batch)
                else:
                    flush(batch)
            else:
                empty_schema = pa.schema([(column, pa.string()) for column in column_names]) if column_names else pa.schema([])
                writer = pq.ParquetWriter(path, empty_schema)
        elif batch:
            flush(batch)
    finally:
        if writer is not None:
            writer.close()
    return row_count


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
