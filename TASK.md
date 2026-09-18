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

## [COMPLETED] Chunk 5: Bidirectional Consensus Local Relaxation (Strategic Subsystem Stability)
* **Goal**: Solve the "Butterfly Effect" and non-deterministic clustering flips in CI/CD while accommodating real intentional refactorings.
* **Status**: Complete (`graphify/cluster.py`).
  - Strict perturbation boundary: $P = \text{TouchedFiles} \cup \text{DirectNeighbors}(\text{TouchedFiles})$. Nodes outside $P$ remain 100% frozen.
  - Pass 1 (A $\to$ Z) and Pass 2 (Z $\to$ A) bidirectional modularity sweeps with inertia threshold ($\lambda = 0.05$).
  - Unanimous consensus commits genuine architectural subsystem migrations.
  - Order-sensitive disagreement retains baseline community and surfaces `borderAmbiguities` in `pacre-delta.json`.
  - Pure Python execution: sub-15ms latency across 500+ nodes (well below the 500ms gate).

## [COMPLETED] Chunk 6: CLI Named Flags & `--pr` Auto Merge-Base Detection
* **Goal**: Support production CI/CD workflows with named parameters and automated base detection.
* **Status**: Complete (`graphify/cli.py`).
  - Supports `graphify diff [--base <commit>] [--head <commit>] [--pr] [--out <path>]`.
  - Automatically detects merge-base via `git merge-base` against `origin/main` / `main` / `origin/master`.
  - Custom output file redirection via `--out`.

## [COMPLETED] Chunk 7: Strict Git Cryptographic Binding & Fail-Fast Error Diagnostics
* **Goal**: Enforce P-ACRE cryptographic ledger integrity by mandating valid Git commit history and providing actionable CI guidance.
* **Status**: Complete (`graphify/cli.py`, `graphify/watch.py`, `tests/test_pacre_delta.py`).
  - Strict Git verification checks `git rev-parse --is-inside-work-tree`.
  - Resolves revisions to full 40-character commit SHAs (`baseCommit` and `headCommit`).
  - Surfaces explicit CI troubleshooting guidance (e.g., `actions/checkout@v4` with `fetch-depth: 0`).
  - Full automated regression suite added in `tests/test_pacre_delta.py`.

