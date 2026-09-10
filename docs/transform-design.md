# Transforming the as-is collections into NMDC ontology shapes

Not implemented. This records the shape of the problem so the decision is not re-derived later.

## What the existing loader produces

The NMDC ontology loader reads the same semsql file and writes two collections:

- `ontology_class_set`: one document per class, carrying `id`, `type`, `name`, `definition`, `alternative_names`, `is_root`, `is_obsolete`, and a `relations` array.
- `ontology_relation_set`: one document per relation, carrying `subject`, `predicate`, `object`, `type`.

Its behaviour has changed across versions, which any transform has to account for:

- Through 0.3.x, both modes populate the embedded `relations` array on each class, so every relation is stored twice, once inline and once standalone.
- From the streaming release, the fast path writes `relations: []` and relations live only in the standalone collection. The slow path still embeds them.

So "the shape the loader writes" is not one shape. A transform should target the standalone collection as the source of truth for relations and leave the embedded array empty, which is where the code is heading and what the only known downstream consumer already assumes.

## Mapping from the as-is collections

Everything needed is present without going back to the ontology file.

| output field | source |
|---|---|
| `id` | `statements.subject` where the subject is a CURIE in the target ontology |
| `name` | `statements.value` where `predicate = 'rdfs:label'` |
| `definition` | `statements.value` where `predicate = 'IAO:0000115'` |
| `alternative_names` | `statements.value` where `predicate` is one of the synonym predicates |
| `is_obsolete` | presence of `predicate = 'owl:deprecated'` |
| `is_root` | subject with no `rdfs:subClassOf` to another term in the ontology |
| relations, direct | `statements` where `predicate` is `rdfs:subClassOf` or `BFO:0000050` |
| relations, entailed | `entailed_edge`, already the transitive closure |

## Things that will bite

**Synonym predicates are several, and they are scoped.** `oio:hasExactSynonym`, `oio:hasRelatedSynonym` and `oio:hasBroadSynonym` are distinct, and the existing loader flattens all of them into one unordered list, discarding the scope. Preserving scope would be an improvement but changes the output shape.

**`oio:hasAlternativeId` is not a synonym.** It is a retired identifier, not a name, and must not be folded into `alternative_names`.

**Ordering must be deterministic.** Building a list from a set produces an order that varies between processes, which makes documents non-reproducible and causes needless rewrites on every reload. Sort explicitly.

**Deprecated terms may be ranks rather than taxa.** In NCBITaxon the deprecated entries are rank terms being migrated to TAXRANK equivalents, not obsolete organisms. Treating them as obsolete classes would be wrong.

**Rank is available and currently unused.** `obo:ncbitaxon#has_rank` and its TAXRANK replacement both carry it. Nothing downstream consumes rank today, but it is the obvious next request from anyone working on isolates.

**Closure predicate naming.** The existing loader labels entailed edges `entailed_isa_partof_closure` even when only `rdfs:subClassOf` was used, which is inaccurate. NCBITaxon's `entailed_edge` contains only `rdfs:subClassOf`, so the accurate label there is `entailed_isa_closure`.

## Why do this in the database rather than in Python

Once the tables are in MongoDB, an aggregation pipeline can build class documents server-side without moving tens of millions of rows through a client. That is the main argument for having the as-is collections at all, beyond simply having the data in the right store.

The counter-argument is that a 52M-row grouping is a heavy job to run on a shared cluster, and it needs to be measured before anyone assumes it is cheaper than the current path.
