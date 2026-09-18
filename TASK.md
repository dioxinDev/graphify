# Task Breakdown: PACRE Delta Contract Enrichment (`pacre-delta.json`)

This document outlines the precise operational chunks required to compute and serialize real symbol diffs, edge changes, and blast radius metrics into `pacre-delta.json` matching the PACRE specification (`FORK.md`).

---

## [COMPLETED] Chunk 1: Symbol & Edge Diff Extractor
* **Goal**: Identify exact added and removed symbols and edges between the baseline cache/graph and the newly parsed/patched graph.
* **Status**: Complete.
  - Compares pre-rebuild and post-rebuild nodes and edges.
  - Emits structured `astDelta.addedSymbols` and `astDelta.removedSymbols` with `{ id, type, line, file }`.
  - Emits structured `astDelta.addedEdges` and `astDelta.removedEdges` with `{ source, target, relation }`.

## [COMPLETED] Chunk 2: Direct & Indirect Downstream Blast Radius Computation
* **Goal**: Compute transitive downstream impact from changed/added symbols using pure-Python graph traversal.
* **Status**: Complete.
  - Extracts 1-hop direct downstream dependents (`directDownstream`).
  - Computes transitive multi-hop downstream impact (`indirectDownstream`) via BFS with zero external runtime dependencies.

## [COMPLETED] Chunk 3: Subsystem Impact Mapping
* **Goal**: Map impacted symbols to their corresponding community/subsystem clusters.
* **Status**: Complete.
  - Reads `community_name` and `community` attributes across all reached symbols.
  - Aggregates affected subsystem identifiers into `blastRadius.impactedSubsystems`.

## [COMPLETED] Chunk 4: Delta Contract Serialization & Integration
* **Goal**: Assemble enriched diffs and blast radius metrics into the structured `pacre-delta.json` schema during `graphify diff`.
* **Status**: Complete.
  - Supports `-z` NUL-byte git-diff parsing with full rename, copy, and conflict handling.
  - Emits fully compliant `pacre-delta.json` to `.graphify-out/pacre-delta.json`.
