# Task Breakdown: PACRE Delta Contract Enrichment (`pacre-delta.json`)

This document outlines the precise, small operational chunks required to compute and serialize real symbol diffs, edge changes, and blast radius metrics into `pacre-delta.json`.

---

## Chunk 1: Symbol & Edge Diff Extractor
* **Goal**: Identify exact added and removed symbols and edges between the baseline cache/graph and the newly parsed/patched graph.
* **Scope**:
  - Compare pre-rebuild and post-rebuild node sets and edge sets for touched/re-extracted files.
  - Populate `astDelta.addedSymbols`, `astDelta.removedSymbols`, `astDelta.addedEdges`, and `astDelta.removedEdges`.

## Chunk 2: Direct & Indirect Downstream Blast Radius Computation
* **Goal**: Compute transitive downstream impact from changed/added symbols using NetworkX graph traversal.
* **Scope**:
  - Extract direct 1-hop downstream dependents (`CALLS`, `IMPORTS`, `EXTENDS`, etc.).
  - Traverse multi-hop downstream dependencies to populate indirect downstream impact sets.

## Chunk 3: Subsystem Impact Mapping
* **Goal**: Map impacted symbols to their corresponding community/subsystem clusters.
* **Scope**:
  - Inspect community cluster assignments from community detection metadata.
  - Aggregate affected subsystem identifiers into `blastRadius.impactedSubsystems`.

## Chunk 4: Delta Contract Serialization & Integration
* **Goal**: Assemble enriched diffs and blast radius metrics into the structured `pacre-delta.json` schema during `graphify diff`.
* **Scope**:
  - Finalize JSON serialization contract matching PACRE's expected schema.
  - Write out `pacre-delta.json` to `.graphify-out/pacre-delta.json`.
