"""Real SQLite fixtures and isolated optional MongoDB access."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from semsql_to_mongo.loader import mongo_client


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    path = tmp_path / "ontology.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE statements (
                stanza TEXT, subject TEXT, predicate TEXT, object TEXT,
                value TEXT, datatype TEXT, language TEXT
            );
            CREATE TABLE entailed_edge (subject TEXT, predicate TEXT, object TEXT);
            CREATE TABLE prefix (prefix TEXT, base TEXT);
            """
        )
        connection.executemany(
            "INSERT INTO statements VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("ont", "ont", "owl:versionIRI", None, "https://example.org/v1", None, None),
                ("ont", "ont", "owl:versionInfo", None, "release 1", None, None),
                ("a", "a", "rdfs:label", None, 'a "quoted"\nlabel', "xsd:string", "en"),
                ("a", "a", "rdfs:subClassOf", "b", None, None, None),
                ("b", "b", "rdfs:label", None, "B", None, None),
            ],
        )
        connection.executemany(
            "INSERT INTO entailed_edge VALUES (?, ?, ?)",
            [("a", "is_a", "b"), ("b", "is_a", "c"), ("a", "is_a", "c")],
        )
        connection.executemany(
            "INSERT INTO prefix VALUES (?, ?)",
            [("ex", "https://example.org/"), ("ex", "https://example.org/"), ("owl", "http://owl/")],
        )
    return path


@pytest.fixture
def scratch_database() -> Iterator[dict[str, Any]]:
    if not os.environ.get("MONGO_PASSWORD"):
        pytest.skip("MONGO_PASSWORD is unset; MongoDB integration tests require a server")
    with mongo_client() as client:
        database_name = f"semsql_test_{uuid4().hex}"
        if database_name in client.list_database_names():
            pytest.fail(f"Scratch database already exists: {database_name}")
        database = client[database_name]
        # Even in an isolated database, avoid all production collection names.
        collections = {
            name: database[f"scratch_{name}_{uuid4().hex}"]
            for name in ("statements", "entailed_edge", "prefix", "_provenance")
        }
        try:
            yield collections
        finally:
            client.drop_database(database_name)
