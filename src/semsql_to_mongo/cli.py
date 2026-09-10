"""Command line interface for the semsql loader."""

import json
import logging
from pathlib import Path

import click

from semsql_to_mongo.loader import LOGGER, NATURAL_KEYS, load, mongo_client, validate_options


@click.command()
@click.option("--sqlite", "path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--mongo-db", envvar="MONGO_DB", required=True, help="Destination database; defaults to MONGO_DB.")
@click.option("--tables", default=",".join(NATURAL_KEYS), show_default=True)
@click.option("--batch-size", default=5000, type=click.IntRange(min=1), show_default=True)
@click.option("--limit", type=click.IntRange(min=0), help="Maximum rows read per table.")
@click.option("--dry-run", is_flag=True, help="Inspect source counts and provenance without MongoDB access.")
def cli(path: Path, mongo_db: str, tables: str, batch_size: int, limit: int | None, dry_run: bool) -> None:
    """Copy semsql SQLite tables unchanged into MongoDB collections."""
    selected = tuple(table.strip() for table in tables.split(","))
    validate_options(selected, batch_size, limit)
    handler = logging.StreamHandler()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        if dry_run:
            report = load(path, tables=selected, batch_size=batch_size, limit=limit, dry_run=True)
        else:
            with mongo_client() as client:
                report = load(path, client[mongo_db], selected, batch_size, limit)
        click.echo(json.dumps(report, default=str, indent=2))
    finally:
        LOGGER.removeHandler(handler)
        handler.close()
