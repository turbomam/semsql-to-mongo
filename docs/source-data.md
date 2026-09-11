# What is actually in a semsql NCBITaxon build

Measured against `ncbitaxon.db`, release `2025-12-03`, and cross-checked against an ENVO build. Everything here is counted, not estimated.

## Only three tables have rows

The file contains 18 base tables, 82 views and 11 indexes. Fifteen of the base tables are empty.

| table | rows |
|---|---|
| `statements` | 21,455,292 |
| `entailed_edge` | 51,991,442 |
| `prefix` | 1,275 |

Empty: `anonymous_class_expression`, `anonymous_expression`, `anonymous_individual_expression`, `anonymous_property_expression`, `has_oio_synonym_statement`, `lexical_problem`, `owl_complex_axiom`, `owl_restriction`, `problem`, `rdf_level_summary_statistic`, `rdf_list_statement`, `relation_graph_construct`, `repair_action`, `subgraph_query`, `term_association`.

**`has_oio_synonym_statement` being an empty base table is a trap.** In stock semsql it is usually a view over `statements`. Here it holds nothing, while the synonym data is present in `statements` under the `oio:has*Synonym` predicates. Code written against that table finds nothing and reports no error.

## `entailed_edge` is single-predicate for this ontology

```sql
SELECT predicate, COUNT(*) FROM entailed_edge GROUP BY predicate;
```

| predicate | n |
|---|---|
| `rdfs:subClassOf` | 51,991,442 |

That is the whole table. ENVO by contrast has 90 predicates in the same table, led by `RO:0002131` (85,125), `rdfs:subClassOf` (75,484), `BFO:0000051` (53,576) and `BFO:0000050` (36,857).

Two consequences. An is_a closure and a combined is_a plus part_of closure are necessarily identical for NCBITaxon, because there are no `part_of` edges to add. And deduplication of `(subject, object)` pairs is unnecessary for a single predicate: the row count equals the distinct-pair count exactly.

The query answers in about seven seconds despite 52M rows, because SQLite serves it from the `entailed_edge_spo` covering index.

## `statements` predicates

26 predicates over 21,455,292 rows.

| predicate | n |
|---|---|
| `rdf:type` | 3,184,892 |
| `oio:hasDbXref` | 2,759,519 |
| `rdfs:label` | 2,708,886 |
| `oio:hasOBONamespace` | 2,708,859 |
| `rdfs:subClassOf` | 2,708,805 |
| `TAXRANK:1000000` | 2,455,030 |
| `obo:ncbitaxon#has_rank` | 2,455,030 |
| `oio:hasSynonymType` | 476,002 |
| `owl:annotatedProperty` / `owl:annotatedSource` / `owl:annotatedTarget` | 476,002 each |
| `oio:hasRelatedSynonym` | 360,017 |
| `oio:hasExactSynonym` | 113,792 |
| `oio:hasAlternativeId` | 94,124 |
| `oio:hasBroadSynonym` | 2,193 |
| `IAO:0100001` | 50 |
| `owl:deprecated` | 50 |
| `rdfs:subPropertyOf` | 15 |
| `oio:hasScope` | 11 |
| `rdfs:comment` | 4 |
| `IAO:0000115` | 2 |
| `dcterms:*`, `owl:versionIRI`, `owl:versionInfo` | 1 each |

Notes that matter for any transform:

- **Class count triangulates to about 2,708,800** from three independent predicates.
- **Synonyms total 476,002**, split across three scopes. Flattening them into one list discards the scope distinction.
- **`oio:hasAlternativeId` is not a synonym.** It is a retired identifier and must not be folded into an alias list.
- **Rank is carried twice**, under `TAXRANK:1000000` and `obo:ncbitaxon#has_rank`, at identical counts. See below for why.
- **Nearly 1.9M rows are OWL axiom reification** (`owl:annotated*`), existing only to annotate the 476,002 synonym assertions.

## All 50 deprecated terms are ranks, not taxa

Every `owl:deprecated` subject is a rank term, each with an `IAO:0100001` replacement pointing at a TAXRANK equivalent:

| deprecated | replaced by |
|---|---|
| `NCBITaxon:species` | `TAXRANK:0000006` |
| `NCBITaxon:genus` | `TAXRANK:0000005` |
| `NCBITaxon:strain` | `TAXRANK:0001001` |
| `obo:ncbitaxon#has_rank` | `TAXRANK:1000000` |
| ... 46 more, all ranks | |

This explains the duplicated rank predicate: the ontology is mid-migration, retaining the deprecated `ncbitaxon#has_rank` alongside its TAXRANK replacement.

**Treating these as obsolete classes would be wrong.** No taxon is deprecated in this release. A transform that maps `owl:deprecated` onto an `is_obsolete` flag for taxa will mark 50 rank terms obsolete and nothing else.

## The `prefix` table is boilerplate, and it is dirty

1,275 rows, but only **489 distinct prefixes** and 501 distinct (prefix, base) pairs. The set is byte-identical between NCBITaxon and ENVO builds, and includes prefixes with no presence in either ontology, so it is a shipped standard map rather than an inventory of the file's content.

- **774 rows are exact duplicates.** 247 prefixes appear four times, one appears eight.
- **12 prefixes map to two different base URIs**, and none collapse under case normalisation. Nine look like legitimate alternates for the same resource. Three carry a different resource's base entirely, while that resource has no prefix row of its own.

Reported upstream: https://github.com/INCATools/semantic-sql/issues/124

Nothing in this repository resolves CURIEs through that table, so it is copied as-is and the duplicates are skipped by the natural-key index.

## File sizes matter for deployment

| | size |
|---|---|
| `ncbitaxon.db.gz` as downloaded | 2.00 GiB |
| `ncbitaxon.db` decompressed | 11.92 GiB |
| both, as the cache leaves them | 14 GiB |

Any environment that fetches and decompresses this file needs headroom for both. See [`docs/operational-constraints.md`](operational-constraints.md).

## The build identifies itself

```
obo:ncbitaxon.owl  owl:versionIRI    obo:ncbitaxon/2025-12-03/ncbitaxon.owl
obo:ncbitaxon.owl  owl:versionInfo   2025-12-03
```

Worth capturing on load. A copy that cannot say which release it holds cannot be compared against another copy, and that is not hypothetical: see [`docs/other-copies.md`](other-copies.md).
