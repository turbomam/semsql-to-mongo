# semsql-to-mongo

Load the populated tables of a [semsql](https://github.com/INCATools/semantic-sql) SQLite ontology build into MongoDB, as-is, with provenance.

## Why this exists

NMDC's data backend is MongoDB. Getting NCBI Taxonomy into that backend is a standing commitment, and MongoDB is where the runtime and the data portal read from. That requirement is what this tool serves: not "query an ontology quickly", which several existing tools already do better, but "put the data in the store the rest of the system uses."

That distinction matters enough to state plainly, because most of the obvious alternatives are faster and still do not satisfy it. See [Alternatives considered](#alternatives-considered).

## What it does

Copies three tables from a semsql `.db` into three MongoDB collections, one document per row, column names preserved. No reshaping, no schema mapping, no inference.

| source table | destination collection |
|---|---|
| `statements` | `statements` |
| `entailed_edge` | `entailed_edge` |
| `prefix` | `prefix` |

Those three are the only tables with rows in a current NCBITaxon build. The other 15 base tables are empty, and the 82 views are derived. Verified against `ncbitaxon.db` (release 2025-12-03) and `envo.db`.

Alongside them the loader writes a `_provenance` document recording the source `owl:versionIRI`, the file checksum, row counts and the load timestamp. This is deliberate: an existing third-party copy of the same data carries no version metadata at all, which makes it impossible to tell which release it holds or whether it has been refreshed. A copy that cannot identify itself is much harder to trust than one that can.

## What it does not do

**No transformation into NMDC schema shapes.** Producing `OntologyClass` and `OntologyRelation` documents is a separate concern, handled today by the NMDC ontology loader. Transforming these as-is collections into that shape is anticipated and sketched in [`docs/transform-design.md`](docs/transform-design.md), but is not implemented here yet.

**No NCBI taxdump support.** Loading directly from the NCBI taxonomy dump files is a reasonable alternative path with different parsing and different failure modes. It belongs in its own repository rather than as a second mode here.

**No closure computation.** `entailed_edge` already contains the transitive closure. Nothing needs deriving.

## Alternatives considered

These were raised in review, or found while looking for prior art. Each is a real option, and the reason for not using it is the same in every case: none of them put the data in MongoDB.

**Query the SQLite file in place.** It is already on disk and already indexed. A `GROUP BY predicate` over 52 million rows in `entailed_edge` answers in about seven seconds from the covering index. If the goal were analysis, this would win outright.

**DuckDB attached to the SQLite file.** `ATTACH ... (TYPE sqlite)` reads the same file with no copy step, and joins it against Parquet and object storage in one query. Analytically this is the strongest option available and it costs nothing to set up.

**The existing lakehouse copy.** A third party already loads these same three tables into a Spark lakehouse, including NCBITaxon at comparable scale with the same closure predicate. It is an older release, it carries no version metadata, and it lacks the deprecation assertions present in current builds, but it exists and it is queryable. Coordinating on refreshing it may be more valuable than duplicating it, and that conversation is worth having independently of this tool.

**A general-purpose LinkML data store.** Its MongoDB insert path cannot consume an iterator, does not batch, and re-reads its input after writing, so it materialises every document before the first write. At tens of millions of rows that is not viable. This is filed upstream. Fixing it there would benefit every consumer and would be a better outcome than routing around it; this repository is the pragmatic short path, not the right long-term answer.

**`sqlite3` piped to `mongoimport`.** Close to workable and worth knowing about. The obstacles are that `.mode json` emits a wrapped array rather than newline-delimited JSON, and that `statements.value` holds definitions containing quotes and newlines, which makes CSV round-tripping risky. A carefully escaped TSV pipeline probably does work, in which case this tool is a thin, testable wrapper around that idea.

**A triplestore.** semsql is derived from RDF, so loading it into a document store moves further from a form that already had query semantics. That is a fair criticism of the destination, and the answer is again that the destination is fixed by what the rest of the system reads.

## Status

Early. The scope above is settled; the implementation is not.

## License

MIT
