# Another copy of this data already exists

Before adding a copy, it is worth knowing what is already out there. A Spark lakehouse maintained by a partner organisation loads the same three semsql tables, including NCBI Taxonomy.

## What it holds

| | that copy | this source file |
|---|---|---|
| `statements`, NCBITaxon subjects | 18,905,715 | 21,455,292 (whole table) |
| `entailed_edge`, NCBITaxon subjects | 64,150,757 | 51,991,442 (whole table) |
| same, both ends NCBITaxon, `rdfs:subClassOf` | 50,918,685 | 51,991,442 |
| closure predicates | `rdfs:subClassOf` only | `rdfs:subClassOf` only |

Like for like, the closures differ by about 2%. Same predicate, same shape, same three tables. It is a real, queryable copy of substantially the same data.

## But it cannot say what it is

The decisive problem is not the 2% gap, it is that the gap cannot be explained. Across roughly 61 ontologies and 42.8M rows, that copy contains exactly **one** `owl:versionIRI` row, no `owl:versionInfo` and no `dcterms:title`. There is no way to determine which NCBI Taxonomy release it holds, whether it is refreshed, or what a future comparison would be comparing against.

This source file, by contrast, states its release in two places.

## The differences are one input event, not a different build

The two copies differ in which predicates appear:

- Present here, absent there: `TAXRANK:1000000` (2,455,030 rows), `owl:deprecated` (46), `IAO:0100001` (46)
- Present there, absent here: `rdfs:isDefinedBy`, `oio:id` (5), a taxslim-namespaced `has_rank` (2), `IAO:0000118` (1)
- Shared predicates run about 2% lower there, matching a 58,220-class difference

It is tempting to read that as a different build pipeline. It is better explained as an older release. The deprecation of `ncbitaxon#has_rank` and the introduction of its `TAXRANK:1000000` replacement are the **same migration event**, so a release predating it necessarily lacks both the replacement predicate and the deprecation assertions. One input difference accounts for three apparent discrepancies.

Supporting detail: that copy's taxslim-namespaced rank statements point at `NCBITaxon:superkingdom` and `NCBITaxon:kingdom`, the very rank terms deprecated in the current release, still in use as live values. And its handful of extra rows cluster on the taxonomy's root path, which reads as residue from a small seed rather than a different pipeline.

Only `rdfs:isDefinedBy` remains unexplained, and one predicate is thin evidence for a build-path claim.

## What to take from this

Duplicating data that already exists deserves justification. The justification here is the destination: that copy lives in a lakehouse, and the requirement is for the document store the rest of the system reads. Coordinating on refreshing and versioning that copy may be worth more than either of us duplicating the other, and that conversation is worth having independently.

The lesson this repository takes from it is narrower and concrete: **record provenance on every load**. A copy that cannot identify its own source is much harder to trust, and the cost of preventing that is one small document.
