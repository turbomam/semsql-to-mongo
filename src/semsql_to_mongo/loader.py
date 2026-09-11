"""Stream semsql rows into MongoDB with duplicate handling and provenance."""

import hashlib
import logging
import os
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.errors import BulkWriteError

LOGGER = logging.getLogger("semsql_to_mongo")
NATURAL_KEYS = {
    "statements": ("subject", "predicate", "object", "value"),
    "entailed_edge": ("subject", "predicate", "object"),
    "prefix": ("prefix", "base"),
}


def validate_options(tables: tuple[str, ...], batch_size: int, limit: int | None) -> None:
    """Reject unsupported tables and invalid bounds before any writes."""
    if not tables or len(set(tables)) != len(tables) or any(table not in NATURAL_KEYS for table in tables):
        raise ValueError("Select distinct tables from statements, entailed_edge, prefix")
    if batch_size < 1 or (limit is not None and limit < 0):
        raise ValueError("batch_size must be positive and limit must be nonnegative")


def iter_rows(connection: sqlite3.Connection, table: str, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield unchanged rows from a cursor, retaining SQLite values and nulls."""
    validate_options((table,), 1, limit)
    query = f'SELECT * FROM "{table}"'
    parameters = () if limit is None else (limit,)
    if limit is not None:
        query += " LIMIT ?"
    with closing(connection.execute(query, parameters)) as cursor:
        columns = [column[0] for column in cursor.description]
        for row in cursor:
            yield dict(zip(columns, row))


def insert_rows(collection: Any, rows: Iterable[dict[str, Any]], batch_size: int) -> dict[str, int]:
    """Insert bounded batches and suppress only confirmed duplicate write errors."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    counts = {"read": 0, "inserted": 0, "skipped": 0}
    batch: list[dict[str, Any]] = []

    def flush() -> None:
        try:
            result = collection.insert_many(batch, ordered=False)
        except BulkWriteError as error:
            details = error.details
            errors = details.get("writeErrors", [])
            if details.get("writeConcernErrors") or not errors or any(item["code"] != 11000 for item in errors):
                raise
            counts["inserted"] += details["nInserted"]
            counts["skipped"] += len(errors)
            LOGGER.info("Skipped %d duplicate rows in this batch (including upstream duplicates)", len(errors))
        else:
            counts["inserted"] += len(result.inserted_ids)
        batch.clear()

    for row in rows:
        batch.append(row)
        counts["read"] += 1
        if len(batch) == batch_size:
            flush()
    if batch:
        flush()
    return counts


def file_checksum(path: Path) -> str:
    """Hash the source in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mongo_client(environment: Mapping[str, str] | None = None) -> MongoClient:
    """Build a client using environment credentials, without a credential URI."""
    env = os.environ if environment is None else environment
    host = env.get("MONGO_HOST", "localhost")
    # PyMongo accepts URIs as hosts; disallow them so credentials have one source.
    if "://" in host or "@" in host:
        raise ValueError("MONGO_HOST must be a hostname, not a connection URI")
    return MongoClient(
        host=host,
        port=int(env.get("MONGO_PORT", "27017")),
        username=env.get("MONGO_USERNAME") or None,
        password=env.get("MONGO_PASSWORD") or None,
        serverSelectionTimeoutMS=10000,
    )


def load(
    path: Path,
    database: Any = None,
    tables: tuple[str, ...] = tuple(NATURAL_KEYS),
    batch_size: int = 5000,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Load selected tables and record provenance only after all writes succeed.

    The limit applies independently to each table. Dry runs inspect the source
    without contacting MongoDB or writing provenance. Keep the source immutable
    during a load so its file checksum identifies the SQLite snapshot.
    """
    validate_options(tables, batch_size, limit)
    path = path.resolve(strict=True)
    if database is None and not dry_run:
        raise ValueError("A MongoDB database is required for a load")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        table_counts = {}
        # Validate every selected schema before creating indexes or inserting data.
        for table in tables:
            with closing(connection.execute(f'SELECT * FROM "{table}" LIMIT 0')) as cursor:
                columns = {column[0] for column in cursor.description}
            if not set(NATURAL_KEYS[table]).issubset(columns):
                raise ValueError(f"Missing natural key columns in {table}")
            if "_id" in columns:
                raise ValueError(f"Source {table} contains _id, which conflicts with MongoDB identity")
            table_counts[table] = {"source_rows": connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}
        ontology = {}
        for predicate in ("owl:versionIRI", "owl:versionInfo"):
            row = connection.execute(
                "SELECT value FROM statements WHERE predicate = ? LIMIT 1", (predicate,)
            ).fetchone()
            ontology[predicate] = None if row is None else row[0]
        provenance = {
            "source_path": str(path),
            "source_size_bytes": path.stat().st_size,
            "source_sha256": file_checksum(path),
            "ontology": ontology,
            "tables": table_counts,
            "tool_version": version("semsql-to-mongo"),
            "limit": limit,
        }
        for table in tables:
            if dry_run:
                table_counts[table].update(read=0, inserted=0, skipped=0)
                continue
            collection = database[table]
            collection.create_index([(key, 1) for key in NATURAL_KEYS[table]], unique=True)
            # Close the cursor before the connection even when a batch fails.
            with closing(iter_rows(connection, table, limit)) as rows:
                table_counts[table].update(insert_rows(collection, rows, batch_size))
            LOGGER.info("%s: %s", table, table_counts[table])
        provenance["timestamp"] = datetime.now(timezone.utc)
        if not dry_run:
            # PyMongo adds _id in place; keep the returned report independent.
            database["_provenance"].insert_one(dict(provenance))
        return provenance
