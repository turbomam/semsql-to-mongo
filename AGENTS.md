# AGENTS.md

Conventions for this repository. Each rule here exists because its absence caused a real problem somewhere, not because it sounded like good practice.

## Project overview

Copies the populated tables of a semsql SQLite ontology build into MongoDB collections, one document per row, unchanged. See `README.md` for why MongoDB specifically, and for the alternatives that were considered and rejected.

Scale is the design constraint: a current NCBITaxon build has 21.5M rows in `statements` and 52M in `entailed_edge`. Anything that holds a full table in memory is wrong here.

## Safeguards for database tests

Any test that writes to MongoDB must:

1. **Use a scratch database name** that cannot collide with real data. Never `nmdc`. Never the production collection names.
2. **Verify the target does not already exist before writing.** If it does, fail loudly so a developer investigates, rather than silently overwriting.
3. **Clean up in a `finally` block**, so a failing assertion does not leave state behind.
4. **Skip cleanly when no database is available**, gated on the `MONGO_*` environment variables, so the suite runs without one.

## Correctness rules

* **Stream, never materialise.** Read with a cursor, write in batches. A function that builds a list of every row will pass its tests on a small ontology and fail in production on a large one.
* **Declare unique indexes before inserting**, so that rerunning a load skips documents that already exist instead of duplicating them. A previous loader in this ecosystem shipped without this and silently doubled its data on any rerun, with no error and no warning.
* **Record provenance on every load**: source version IRI, file checksum, row counts, timestamp. A copy that cannot say which release it holds cannot be reasoned about later, and this has already caused confusion with an existing third-party copy of the same data.
* **Fail fast.** Avoid `try`/`except` outside test cleanup; masking an error here means writing wrong data rather than writing none.

## Test rules

* **A test must be able to fail.** Before asserting a property, assert that the fixture actually exercises it. A test that checks "every alias list is sorted" passes vacuously if no list has two elements, and then guards nothing.
* **Prefer real data over mocks.** Mocks cannot be wrong about what SQLite or MongoDB actually do, which is exactly where the bugs are.
* **Do not weaken an assertion to make a test pass.** If a test fails and the fix is not obvious, stop and ask.
* Functional pytest style, not unittest classes. Use `@pytest.mark.parametrize` for input combinations.

## Secrets

* Credentials come from the environment only. Never in a connection string committed to the repo, never in `argv`, never printed.
* `gitleaks` runs pre-commit.
* Note that some libraries in this space log connection details, including passwords, at INFO level. Do not raise the root log level in a CLI entry point; raise only this package's own logger.

## Style

* Type hints and docstrings on everything public.
* Comments explain why, not what. A bare `sorted()` with no comment is the kind of thing a later reader deletes.
* Plain language in commit messages, issues and pull requests. No em dashes, no invented jargon.

## Build and test

Managed with `uv`. Never use `pip install` directly.

```
uv sync
uv run pytest
uv run ruff check .
```
