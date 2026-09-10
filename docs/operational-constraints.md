# Operational constraints in the target environment

Measured against the production MongoDB and taken from the deployed worker configuration. These are the numbers a load has to live inside.

## The worker

The scheduled loader runs on a worker with these limits:

```yaml
limits:
  cpu: 6
  ephemeral-storage: 9Gi
  memory: 12Gi
```

**Ephemeral storage is the binding constraint, and it is easy to miss.** Attention has gone to the 12 GiB memory limit, but the semsql artifact is 11.92 GiB decompressed plus a 2.00 GiB archive, 14 GiB together as the download cache leaves them. That exceeds 9 GiB before any loading begins.

Anything that fetches and decompresses the source on the worker fails on disk regardless of how well it streams. The options are a mounted volume, raised ephemeral storage, decompression that never lands the full file, or fetching the artifact somewhere other than the worker.

## The database

| measure | value |
|---|---|
| logical `dataSize` | 61.2 GB |
| on-disk `storageSize` | 9.9 GB |
| index size | 10.4 GB |
| server version | 8.2.3 |

Two things follow.

**Compression is roughly 6x**, so logical size badly overstates disk cost. Estimating a new collection's footprint from document sizes without accounting for that will overshoot by a wide margin.

**Indexes already cost more than the data.** At 9.9 GB of data against 10.4 GB of indexes, an index on a 52M-row collection is the expensive part of adding one, not the rows.

**Views are already in production use** on this server, so they are an available mechanism rather than a novel one.

## Existing ontology collections

| | documents | avg doc |
|---|---|---|
| `ontology_class_set` | 22,722 | 3,833 bytes |
| `ontology_relation_set` | 561,169 | 150 bytes |

Present ontologies: UBERON 16,358, ENVO 4,366, PO 1,998. NCBI Taxonomy is **not loaded**, so nothing has diverged yet and the shape questions below are still open rather than already broken.

**Relations are currently stored twice.** 20,551 of the class documents carry an embedded relations array, holding 561,022 objects in total, against 561,169 documents in the standalone collection. Same data, two copies.

That embedding is what makes the average class document 3,833 bytes. The same loader's fast path, which writes an empty array instead, produces 379-byte class documents on the same ontology. **Roughly a 10x difference in class document size**, which at NCBITaxon's 2.7M classes is the single largest disk lever available.

## Neither collection is in the schema

`ontology_class_set` is defined as a slot but is not attached to the `Database` class. `ontology_relation_set` is not defined anywhere; it appears once, inside a prose comment. Confirmed against the generated Python: neither is a field on `Database`.

Consequently the public API rejects both. `/nmdcschema/ontology_class_set` returns an error listing the 19 collections it will serve, and the OpenAPI specification contains no ontology, taxon or term route at all. Anything reading these collections is doing so through a direct database connection.

The schema does model relations as inlined inside the class, with `inlined: true` and `inlined_as_list: true`. So the schema and the implementation have disagreed since the collections were introduced, and the disagreement has gone unnoticed because the slow path does both.
