# Task Breakdown: Incremental AST Parsing & Graph Patching (`graphify-incremental`)

This document outlines the precise, small operational chunks required to implement sub-second incremental AST parsing and graph patching, as specified in `FORK.md`.

---

## Chunk 1: Content Hashing & Persistent Manifest Store
* **Goal**: Establish local cache persistence in `.graphify/cache/` to track file content hashes, modification timestamps (`mtime`), and extracted AST symbols/edges.
* **Scope**:
  - Implement SHA-256 file hashing utility.
  - Create a manifest store (JSON or SQLite) mapping relative file paths to `{ content_hash, mtime, symbols, edges }`.
  - Add cache loading and saving helpers in `graphify/cache.py` (or a dedicated incremental module).

## Chunk 2: Git Diff Ingestion Hook
* **Goal**: Detect exact change sets between revisions without walking the entire repository.
* **Scope**:
  - Add CLI support for `graphify diff --base <commit> --head <commit>` (or auto-detect against merge-base).
  - Execute `git diff --name-status` to categorize files into:
    - **Added** ($A$)
    - **Modified** ($M$)
    - **Deleted** ($D$)
    - **Renamed** ($R$)
  - Fallback to content-hash comparison if Git is unavailable.

## Chunk 3: Surgical Graph Pruning
* **Goal**: Remove stale nodes and outgoing edges for deleted and modified files from the loaded graph state.
* **Scope**:
  - Load base graph from cache.
  - For each file in $D \cup M$, identify its associated symbol nodes and remove them along with their outgoing edges (`CALLS`, `IMPORTS`, `EXTENDS`, `IMPLEMENTS`, etc.).
  - Remove file-level records and clean up orphaned external stubs where applicable.

## Chunk 4: Targeted Tree-sitter Reparsing
* **Goal**: Parse *only* the touched files ($A \cup M$) using Tree-sitter instead of a full recursive directory walk.
* **Scope**:
  - Invoke language extractors selectively on files in $A \cup M$.
  - Generate fresh AST node and edge dictionaries for the modified subset.
  - Update the persistent manifest with new content hashes and extracted elements.

## Chunk 5: Graph Splicing & Delta Contract Emission
* **Goal**: Splice new AST nodes and edges into the existing graph and emit the PACRE delta contract (`pacre-delta.json`).
* **Scope**:
  - Add new/modified nodes and edges to the NetworkX/graph store.
  - Re-resolve cross-file references and link new call sites to existing targets.
  - Serialize the patched graph (`graph.json`) and generate `pacre-delta.json` detailing added/removed symbols, edge mutations, and computed blast radius.
