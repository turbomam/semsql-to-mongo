# Tooling evaluation

Measured, not assumed. Each entry records what was tried, what happened, and what it means for this repository.

## Reading semsql

**DuckDB, attached directly.** Works, with no copy step:

```sql
INSTALL sqlite; LOAD sqlite;
ATTACH 'ncbitaxon.db' AS nt (TYPE sqlite);
SELECT predicate, COUNT(*) FROM nt.entailed_edge GROUP BY predicate;
```

Returns the same 51,991,442 in seconds, and joins against Parquet and object storage in the same query. For analysis this is the strongest option available and it costs nothing to set up. It does not put anything in the destination store, which is the requirement here.

**A general-purpose LinkML store, `sqlite:` handle.** Fails on attach. That handle routes through DuckDB, which cannot parse one of the 82 semsql views:

```
Failed to prepare query "(SELECT * FROM owl_reified_axiom) UNION (SELECT NULL AS id, statements.* FROM statements)": near "(": syntax error
```

The failure is in enumerating collections, not in reading data, so it is a "skip views that do not parse" problem rather than anything deep.

**The same store, `ibis+sqlite` handle.** Attaches correctly and reports accurate counts:

```
collections found: 100
includes the three populated tables: True
entailed_edge size: 424098   (ENVO)
```

But paged iteration raises immediately:

```
TypeError: IbisCollection.find() got multiple values for keyword argument 'limit'
```

The base class calls `self.find(where=..., offset=..., limit=page_size, **kwargs)` while the ibis implementation declares `find(self, where=None, **kwargs)`. So streaming reads through that abstraction are unavailable until the signature is reconciled.

## Writing to the document store

**The same store's `insert`, with caller-side batching.** Works, and the volume concern that first appeared to rule it out does not hold. 60,000 documents in batches of 5,000:

```
rows inserted   : 60000
wall seconds    : 0.7
peak python mem : 2.8 MiB
```

Memory is bounded by batch size. The post-insert hook builds one patch per object but only for the objects in that call, so it is bounded too.

**What does block an idempotent load** is narrower and was found by testing a rerun against a unique index:

```
BulkWriteError: nInserted = 0, writeErrors = 1, first code = 11000
```

Two problems in that one result. `insert_many` is called without `ordered=False`, so a batch mixing new and existing documents stops at the first collision and abandons the rest. And `BulkWriteError` is not caught, so distinguishing "already present" from a real write failure is left to the caller, who has to reach past the abstraction to do it.

## Command-line alternatives

**`sqlite3` piped to `mongoimport`.** Close to workable. Two obstacles: `.mode json` emits a wrapped array rather than newline-delimited JSON, so a multi-gigabyte stream would need bracket and comma stripping; and `.mode csv` risks mangling `statements.value`, which holds definitions containing quotes and newlines. A carefully escaped tab-separated pipeline probably does work.

## Reading needs no third-party library at all

The two read-side failures above are worth reporting, but they are not obstacles this project has to clear, because the premise behind them was wrong.

`sqlite3` is in the Python standard library. Reading a SQLite file needs no dependency, and a cursor streams natively, which is the only property that matters at this scale. Every measurement in [`source-data.md`](source-data.md), including a `GROUP BY` over 52 million rows that returned in about seven seconds, was taken through stdlib `sqlite3`.

DuckDB and ibis entered the picture only because the shared library's SQLite handles route through them. Adopting that path would mean adding two substantial dependencies, and waiting on two upstream fixes, in order to wrap something the standard library already does well for this access pattern. One of the two cannot open a semsql build at all.

So for reads, the established library is the standard library.

## Writing is a different case

There the shared library is not wrapping stdlib. It provides connection handling, a collection abstraction and the interface other tools in this ecosystem already use, over a driver that would otherwise be called directly. Its gaps are small, specific and worth closing upstream rather than routing around, and closing them benefits every consumer rather than just this repository.

## The resulting choice

Standard-library `sqlite3` for reads. The shared library for writes, once the write-path gaps are addressed upstream; the driver directly until then, with the gaps tracked rather than silently worked around.

This is deliberately not symmetrical. Using an abstraction on both halves for consistency's sake would cost two dependencies and two blocked fixes, and would make the read path slower and more fragile than the eight lines of stdlib it replaced. Consistency is not worth that here.

The two read-side defects are reported upstream as a courtesy, since both are real and reproduced, and neither is specific to this project: the DuckDB handle cannot open any semsql build, and paged iteration is broken for every collection on the ibis backend.
