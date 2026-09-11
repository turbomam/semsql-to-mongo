"""Verify streaming, source fidelity, failures, and MongoDB behavior."""

import hashlib
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner
from pymongo.errors import BulkWriteError

from semsql_to_mongo.cli import cli
from semsql_to_mongo.loader import NATURAL_KEYS, insert_rows, iter_rows, load, mongo_client


def test_streaming_does_not_read_ahead(sqlite_path: Path) -> None:
    produced = 0
    calls = 0
    sizes = []

    def rows() -> Iterator[dict[str, Any]]:
        nonlocal produced
        with closing(sqlite3.connect(sqlite_path)) as connection:
            for row in iter_rows(connection, "statements"):
                produced += 1
                yield row

    def insert_many(batch: list[dict[str, Any]], ordered: bool) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert produced == 2
        assert ordered is False
        sizes.append(len(batch))
        return SimpleNamespace(inserted_ids=list(range(len(batch))))

    result = insert_rows(SimpleNamespace(insert_many=insert_many), rows(), 2)
    assert produced == 5
    assert calls == 3
    assert sizes == [2, 2, 1]
    assert result == {"read": 5, "inserted": 5, "skipped": 0}


@pytest.mark.parametrize("table,expected", [("statements", 5), ("entailed_edge", 3), ("prefix", 3)])
def test_real_sqlite_rows(sqlite_path: Path, table: str, expected: int) -> None:
    with closing(sqlite3.connect(sqlite_path)) as connection:
        source = connection.execute(f'SELECT * FROM "{table}"')
        columns = tuple(item[0] for item in source.description)
        source_rows = list(source)
        rows = list(iter_rows(connection, table))
    assert len(source_rows) == expected
    assert len(rows) == expected
    assert all(tuple(row) == columns for row in rows)
    assert [tuple(row.values()) for row in rows] == source_rows
    if table == "statements":
        assert any(value is None for row in source_rows for value in row)
        assert rows[2]["value"] == 'a "quoted"\nlabel'
        assert rows[2]["language"] == "en"


@pytest.mark.parametrize("limit,expected", [(None, 5), (0, 0), (1, 1), (4, 4), (10, 5)])
def test_limits(sqlite_path: Path, limit: int | None, expected: int) -> None:
    with closing(sqlite3.connect(sqlite_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 5
        assert len(list(iter_rows(connection, "statements", limit))) == expected


def test_duplicate_batch_uses_reported_counts_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    calls = 0

    def insert_many(batch: list[dict[str, Any]], ordered: bool) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BulkWriteError({"writeErrors": [{"code": 11000}], "nInserted": 0, "writeConcernErrors": []})
        return SimpleNamespace(inserted_ids=[1])

    with caplog.at_level(logging.INFO, logger="semsql_to_mongo"):
        counts = insert_rows(SimpleNamespace(insert_many=insert_many), ({"x": i} for i in range(3)), 2)
    assert calls == 2
    # The intentionally partial server report proves nInserted is not inferred.
    assert counts == {"read": 3, "inserted": 1, "skipped": 1}
    assert "Skipped 1 duplicate rows" in caplog.text


@pytest.mark.parametrize(
    "details",
    [
        {"writeErrors": [{"code": 11000}, {"code": 121}], "nInserted": 0},
        {"writeErrors": [{"code": 121}], "nInserted": 0},
        {"writeErrors": [{"code": 11000}], "writeConcernErrors": [{"code": 64}], "nInserted": 0},
        {"writeErrors": [], "writeConcernErrors": [{"code": 64}], "nInserted": 1},
        {"writeErrors": [], "nInserted": 0},
    ],
)
def test_bulk_errors_propagate(details: dict[str, Any]) -> None:
    error = BulkWriteError(details)

    def insert_many(batch: list[dict[str, Any]], ordered: bool) -> None:
        raise error

    with pytest.raises(BulkWriteError) as caught:
        insert_rows(SimpleNamespace(insert_many=insert_many), iter([{"x": 1}]), 1)
    assert caught.value is error


@pytest.mark.parametrize("missing_versions", [False, True])
def test_dry_run_provenance(sqlite_path: Path, missing_versions: bool) -> None:
    if missing_versions:
        with closing(sqlite3.connect(sqlite_path)) as connection, connection:
            assert connection.execute("DELETE FROM statements WHERE predicate LIKE 'owl:version%'").rowcount == 2
    report = load(sqlite_path, dry_run=True)
    assert report["source_path"] == str(sqlite_path)
    assert report["source_size_bytes"] == sqlite_path.stat().st_size > 0
    assert report["source_sha256"] == hashlib.sha256(sqlite_path.read_bytes()).hexdigest()
    assert report["tool_version"] == version("semsql-to-mongo")
    assert report["timestamp"].utcoffset().total_seconds() == 0
    assert report["ontology"] == {
        "owl:versionIRI": None if missing_versions else "https://example.org/v1",
        "owl:versionInfo": None if missing_versions else "release 1",
    }
    assert report["tables"]["prefix"] == {"source_rows": 3, "read": 0, "inserted": 0, "skipped": 0}


@pytest.mark.parametrize(
    "tables,batch_size,limit",
    [((), 1, None), (("bad",), 1, None), (("prefix", "prefix"), 1, None), (("prefix",), 0, None), (("prefix",), 1, -1)],
)
def test_invalid_options(sqlite_path: Path, tables: tuple[str, ...], batch_size: int, limit: int | None) -> None:
    with pytest.raises(ValueError):
        load(sqlite_path, tables=tables, batch_size=batch_size, limit=limit, dry_run=True)


def test_cli_dry_run_uses_environment_without_mongo(sqlite_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGO_DB", "scratch_cli")
    monkeypatch.setenv("MONGO_HOST", "invalid://host")
    root_level = logging.getLogger().level
    result = CliRunner().invoke(cli, ["--sqlite", str(sqlite_path), "--dry-run", "--tables", "prefix"])
    assert result.exit_code == 0, result.output
    assert '"source_rows": 3' in result.output
    assert '"statements":' not in result.output
    assert logging.getLogger().level == root_level


def test_uri_host_rejected_without_echoing_secret() -> None:
    with pytest.raises(ValueError) as error:
        mongo_client({"MONGO_HOST": "mongodb://user:secret@host"})
    assert "secret" not in str(error.value)


def test_real_mongo_idempotency_and_fidelity(sqlite_path: Path, scratch_database: dict[str, Any]) -> None:
    first = load(sqlite_path, scratch_database, batch_size=2)
    assert first["tables"]["prefix"] == {"source_rows": 3, "read": 3, "inserted": 2, "skipped": 1}
    with closing(sqlite3.connect(sqlite_path)) as connection:
        for table, keys in NATURAL_KEYS.items():
            expected = list(iter_rows(connection, table))
            assert len(expected) >= 3
            actual = list(scratch_database[table].find({}, {"_id": 0}))
            assert len(actual) == (2 if table == "prefix" else len(expected))
            assert all(row in actual for row in expected)
            indexes = list(scratch_database[table].list_indexes())
            assert len(indexes) == 2
            assert any(index.get("unique") and tuple(index["key"]) == keys for index in indexes)
    second = load(sqlite_path, scratch_database, batch_size=2)
    assert second["tables"]["statements"]["inserted"] == 0
    assert second["tables"]["statements"]["skipped"] == 5
    assert second["tables"]["entailed_edge"]["skipped"] == 3
    assert second["tables"]["prefix"]["skipped"] == 3
    assert scratch_database["_provenance"].count_documents({}) == 2
    saved = scratch_database["_provenance"].find_one({})
    assert saved["ontology"] == first["ontology"]
    assert saved["source_sha256"] == first["source_sha256"]
    assert saved["tables"] == first["tables"]


def test_real_mongo_limit_and_selection(sqlite_path: Path, scratch_database: dict[str, Any]) -> None:
    report = load(sqlite_path, scratch_database, tables=("statements",), batch_size=1, limit=2)
    assert report["tables"]["statements"] == {"source_rows": 5, "read": 2, "inserted": 2, "skipped": 0}
    assert scratch_database["statements"].count_documents({}) == 2
    assert scratch_database["prefix"].count_documents({}) == 0


@pytest.mark.parametrize("fail_write", [False, True])
def test_indexes_precede_inserts_and_provenance_requires_success(sqlite_path: Path, fail_write: bool) -> None:
    events = []
    failure = RuntimeError("write failed")

    def collection(table: str) -> Any:
        def create_index(keys: list[tuple[str, int]], unique: bool) -> None:
            assert keys == [(key, 1) for key in NATURAL_KEYS[table]]
            assert unique is True
            events.append((table, "index"))

        def insert_many(batch: list[dict[str, Any]], ordered: bool) -> Any:
            assert (table, "index") in events
            assert ordered is False
            events.append((table, "insert"))
            if fail_write:
                raise failure
            return SimpleNamespace(inserted_ids=list(range(len(batch))))

        return SimpleNamespace(create_index=create_index, insert_many=insert_many)

    def insert_one(document: dict[str, Any]) -> None:
        assert all((table, "insert") in events for table in NATURAL_KEYS)
        events.append(("_provenance", "insert"))

    database = {table: collection(table) for table in NATURAL_KEYS}
    database["_provenance"] = SimpleNamespace(insert_one=insert_one)
    if fail_write:
        with pytest.raises(RuntimeError) as caught:
            load(sqlite_path, database, batch_size=2)
        assert caught.value is failure
        assert events == [("statements", "index"), ("statements", "insert")]
    else:
        load(sqlite_path, database, batch_size=2)
        assert len(events) == 11
        assert events[-1] == ("_provenance", "insert")


def test_schema_failure_before_writes(sqlite_path: Path) -> None:
    with closing(sqlite3.connect(sqlite_path)) as connection, connection:
        connection.execute("DROP TABLE prefix")
        connection.execute("CREATE TABLE prefix (prefix TEXT)")
    # An empty database mapping would raise KeyError if writes began too soon.
    with pytest.raises(ValueError, match="Missing natural key columns in prefix"):
        load(sqlite_path, {})


def test_missing_source_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        load(path, dry_run=True)
    assert not path.exists()


def test_empty_table(sqlite_path: Path) -> None:
    with closing(sqlite3.connect(sqlite_path)) as connection, connection:
        assert connection.execute("DELETE FROM prefix").rowcount == 3
    with closing(sqlite3.connect(sqlite_path)) as connection:
        # No insert_many attribute: any attempt to write an empty batch fails.
        assert insert_rows(SimpleNamespace(), iter_rows(connection, "prefix"), 2) == {
            "read": 0,
            "inserted": 0,
            "skipped": 0,
        }


def test_sqlite_cursor_never_fetches_all(sqlite_path: Path) -> None:
    class _StreamingCursor(sqlite3.Cursor):
        def fetchall(self) -> list[Any]:
            raise AssertionError("The SQLite reader must iterate, never fetchall")

    class _StreamingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
            return self.cursor(factory=_StreamingCursor).execute(sql, parameters)

    # These are real SQLite connections and cursors, with eager reads prohibited.
    with closing(sqlite3.connect(sqlite_path, factory=_StreamingConnection)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 5
        assert sum(1 for _ in iter_rows(connection, "statements")) == 5


def test_dry_run_does_not_require_a_destination(sqlite_path, monkeypatch):
    """A dry run must not demand a MongoDB it never contacts.

    Requiring `--mongo-db` under `--dry-run` put friction on the one mode that
    cannot need it. The check moved into the command body so a real load still
    fails early, with a message saying why, rather than click's generic one.
    """
    from click.testing import CliRunner

    from semsql_to_mongo.cli import cli

    monkeypatch.delenv("MONGO_DB", raising=False)

    result = CliRunner().invoke(cli, ["--sqlite", str(sqlite_path), "--dry-run"])
    assert result.exit_code == 0, result.output

    # And the inverse, or the test above would pass on a command that never checks.
    result = CliRunner().invoke(cli, ["--sqlite", str(sqlite_path)])
    assert result.exit_code != 0
    assert "--mongo-db is required unless --dry-run" in result.output
