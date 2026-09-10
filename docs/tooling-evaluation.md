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

## Where that leaves this repository

The read side and the write side each have one specific gap in the shared library, and both look small. Closing them would let this loader use the common abstraction for both halves rather than adding another bespoke writer, which is the better outcome for everyone downstream.

Until then the loader talks to the driver directly, and the gaps are tracked upstream rather than worked around silently.
