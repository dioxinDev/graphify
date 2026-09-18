# Project Handover & Forking Specification: Graphify Incremental Engine (`graphify-incremental` / `pacre-graph`)

> **Target Repository for Forking**: [https://github.com/Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify)  
> **Downstream Consumer**: **PACRE** (PR Architecture Compliance & Review Engine)  
> **Objective**: Fork Graphify to introduce **sub-second incremental git-diff AST parsing and graph patching** for CI/CD Pull Request workflows.

---

## 1. Executive Summary & Problem Statement

### 1.1 Context
**PACRE** is an architectural compliance and PR review engine. It computes transitive blast radius, checks architectural constraints (`AGENTS.md`), logs cryptographic audit ledgers, and generates topologically sorted human review sequences.

To support enterprise polyglot repositories (Python, Go, Rust, Java, C++, TypeScript, etc.), PACRE requires deep, entity-level AST call graphs without maintaining custom AST lexical scanners in-house.

### 1.2 The Gap in Graphify
**Graphify** (by Graphify-Labs) is an open-source knowledge-graph builder that uses Tree-sitter to map 40+ programming languages into entity-level knowledge graphs (files, classes, functions, calls, inheritance, Leiden community detection).

However, Graphify is strictly a **whole-codebase batch scanner**:
1. It walks the entire directory tree on every invocation.
2. It parses all files from scratch using Tree-sitter.
3. It constructs an in-memory graph and runs global Leiden community detection.
4. It outputs a static `graph.json`, `graph.html`, and `GRAPH_REPORT.md`.

### 1.3 The Core Bottleneck
In a CI/CD Pull Request lifecycle, developers cannot wait 2 to 5 minutes for a full repository re-scan on every commit. PACRE requires **sub-second latency** (< 500ms) on a 2-file PR diff in a 10,000-file repository.

### 1.4 The Fork's Mission
Transform Graphify from a **batch-only indexer** into an **incremental, revision-aware code graph engine** capable of mutating an existing cached graph in response to a Git diff.

---

## 2. Architectural Differences: Upstream vs. Fork

| Capability | Upstream Graphify | Forked Engine (`graphify-incremental`) |
| :--- | :--- | :--- |
| **Execution Mode** | Full scan only (`graphify .`) | Full scan + Incremental diff (`graphify --diff main...HEAD`) |
| **Parsing Target** | 100% of files in workspace | Only touched files in `git diff` |
| **Graph Construction**| Recreated from scratch in memory | Loaded from cached persistent store, patched in-memory |
| **Community Detection**| Global Leiden algorithm on every run | Frozen baseline clusters; new files inherit nearest cluster |
| **Execution Speed** | 30s – 5min depending on repo size | < 500ms on typical PR diffs (1–10 files) |
| **Primary Output** | Static `graph.json` / `graph.html` | Patched `graph.json` + surgical `delta.json` for PACRE |

---

## 3. Technical Requirements & Implementation Blueprint

The agent assigned to this fork must implement five key components:

### Component 1: Persistent Graph Storage & Content Hashing
* **Storage Engine**: Store the graph in a fast local cache format (e.g. SQLite database or indexed msgpack/pickle) in `.graphify/cache/`.
* **Manifest**: Maintain a table or file mapping `file_path -> { content_hash, mtime, symbol_ids }`.
* **CLI Behavior**: When running in baseline mode (`graphify index --full`), index the entire repository and persist the graph state.

### Component 2: Git Diff Ingestion Hook
* Add CLI flags:
  ```bash
  graphify diff --base <commit-ish> --head <commit-ish>
  # or auto-detect against merge-base:
  graphify diff --pr
  ```
* **Change Set Detection**:
  - Run `git diff --name-status <base> <head>` to obtain exact lists of:
    - **Added files** ($A$)
    - **Modified files** ($M$)
    - **Deleted files** ($D$)
    - **Renamed files** ($R$)
* **Fallback**: If Git is not present, compute deltas via content hash comparison against the persistent manifest.

### Component 3: Surgical Graph Mutation Engine
When an incremental run is triggered for modified files $\{f_1, f_2, ...\}$:
1. **Node & Outgoing Edge Pruning**:
   - For all deleted ($D$) and modified ($M$) files, look up existing symbols in the cache.
   - Remove outgoing edges (`CALLS`, `IMPORTS`, `EXTENDS`, `IMPLEMENTS`) originating from those symbols.
   - For deleted files, remove node records entirely.
2. **Targeted Tree-sitter Reparsing**:
   - Invoke Tree-sitter parsers **only** on files in $A \cup M$.
   - Extract new AST entities (functions, methods, classes, imports, call expressions).
3. **Graph Splicing & Link Resolution**:
   - Insert the newly parsed symbols into the graph.
   - Re-link cross-file edges (connect new call expressions to existing target symbols in the graph).
   - Invalidate/re-evaluate incoming edges pointing to modified symbol signatures.

### Component 4: Deterministic Subsystem & Community Detection Strategy
* **The Problem**: 
  - Standard community detection (Leiden/Louvain) optimizes a global modularity function ($Q$). Because it employs stochastic heuristics and arbitrary tie-breaking, re-running it globally on a 2-line PR causes the "Butterfly Effect": unrelated clusters 50 files away flip identities.
  - In PACRE, non-deterministic subsystem assignment is a fatal flaw: it breaks cryptographic audit ledgers (`ledgerWriter.ts`), triggers false-positive boundary violations, and destabilizes CI checks.
* **The Core Invariant: 100% Bit-Exact Determinism**:
  - Given the same base commit and diff, the engine must produce identical subsystem allocations every single time.
* **Order-of-Arrival Bias & Mitigation (Bidirectional Consensus)**:
  - If a local perturbation set $P = \text{TouchedFiles} \cup \text{DirectNeighbors}(TouchedFiles)$ is evaluated in alphabetical order ($A \to Z$), early nodes can exert an artificial gravitational pull on later nodes.
  - **The Recommended Mitigation: Bidirectional Consensus Relaxation**:
    1. **Pass 1 (Forward)**: Evaluate local modularity $\Delta Q$ across $P$ in lexicographical order ($A \to Z$) with an inertia threshold $\lambda \approx 0.05$.
    2. **Pass 2 (Reverse)**: Evaluate independently from the same baseline in reverse lexicographical order ($Z \to A$).
    3. **Consensus**:
       - If $C_{fwd}(u) == C_{rev}(u)$, commit the migration to the new subsystem with high confidence.
       - If $C_{fwd}(u) \ne C_{rev}(u)$ (order-sensitive boundary ambiguity), **retain the baseline subsystem** and tag the node as an architectural border ambiguity in `pacre-delta.json`.
* **Pragmatic Tiering for the Implementing Agent (The Reality-Check)**:
  - *Tier 1 (MVP)*: **Frozen Baseline**. Keep all existing files locked to their baseline subsystem; assign newly created files to the dominant subsystem of their directory or immediate neighbors.
  - *Tier 2 (Production)*: **Bidirectional Consensus Local Relaxation** (as specified above), allowing refactored files to migrate when both forward and reverse sweeps agree.
  - *Tier 3 (Mainline Convergence)*: Full Leiden re-clustering runs *only* in background CI when merging into `main`, stabilized using the Hungarian Algorithm (bipartite maximum weight matching) to prevent cluster label churn.

### Component 5: PACRE Delta Contract Output (`delta.json`)
In addition to updating the persistent graph, emit a machine-readable `pacre-delta.json` tailored for PACRE consumption:

```json
{
  "version": "1.0.0",
  "baseCommit": "a1b2c3d",
  "headCommit": "e5f6g7h",
  "changes": {
    "filesAdded": ["src/api/v2/auth.py"],
    "filesModified": ["src/services/session.py"],
    "filesDeleted": []
  },
  "astDelta": {
    "addedSymbols": [
      { "id": "src/api/v2/auth.py:verify_token", "type": "function", "line": 42 }
    ],
    "removedSymbols": [
      { "id": "src/services/session.py:legacy_token_check", "type": "function" }
    ],
    "addedEdges": [
      {
        "source": "src/api/v2/auth.py:verify_token",
        "target": "src/db/models.py:User",
        "relation": "CALLS"
      }
    ],
    "removedEdges": []
  },
  "blastRadius": {
    "directDownstream": ["src/routes/login.py"],
    "indirectDownstream": ["src/middleware/auth_gate.py"],
    "impactedSubsystems": ["AUTH_SUBSYSTEM", "API_GATEWAY"]
  }
}
```

---

## 4. Upstream Repository Inspection & Key Code Targets

When cloning `https://github.com/Graphify-Labs/graphify`, the implementing agent should immediately locate and inspect:

1. **CLI Entry Point**: Typically `graphify/cli.py` or `main.py`.
   - Identify where arguments are parsed and where the global extraction pipeline is triggered.
2. **Extraction Layer**: Usually under `graphify/extractors/` or `graphify/parsers/`.
   - Identify how Tree-sitter grammars are loaded and how files are dispatched to language parsers.
   - Ensure individual file parsing can be called standalone without traversing `os.walk()`.
3. **Graph Model & Builder**: Look for `graphify/graph/` or NetworkX / igraph bindings.
   - Inspect the node schema (`Node`, `Edge`, symbol identifiers).
   - Identify how edges are created and if node deletion / edge removal is natively supported.
4. **Community Detection Module**: Find where Leiden or Louvain is called (e.g. `leidenalg` or `cdlib`).
   - Extract the community assignment step into a standalone function that can be bypassed in `--incremental` mode.

---

## 5. PACRE Integration Hook (TypeScript Side)

Once the forked Python engine emits `pacre-delta.json`, PACRE will ingest it via an adapter:

```
[PR Webhook in CI]
       │
       ▼
[python -m graphify diff --base origin/main --head HEAD --out pacre-delta.json] (Executes in < 500ms)
       │
       ▼
[PACRE GraphifyDeltaAdapter.ts]
       │
       ├─➔ Feeds touched symbols into `blastRadius.ts` (Transitive propagation)
       ├─➔ Feeds changed edges into `astRuleEvaluator.ts` (AGENTS.md boundary enforcement)
       ├─➔ Appends compliance state to `ledgerWriter.ts` (Cryptographic audit ledger)
       └─➔ Sequences files in `reviewSequencer.ts` (Topological human review order)
```

---

## 6. Success Metrics & Quality Gates for the Fork

1. **Performance Gate**:
   - Baseline cold start (`graphify index --full`) on a 5,000-file repository: Under 60 seconds.
   - Incremental diff (`graphify diff --base ...`) on 3 modified files: **< 500 milliseconds**.
2. **Determinism Gate**:
   - Re-running the incremental diff twice on the same commit must produce identical edge sets and content hashes.
3. **Zero Upstream Breaking Changes**:
   - The original `graphify .` command must continue to work unchanged for existing users.
4. **Clean Exit Codes**:
   - In CI pipelines, return `0` on successful graph diffing, non-zero with clean stderr diagnostics on syntax or merge errors.

---

## 7. Operational Directive & Reality-Check for the Assigned Agent

> **Important Advisory to the Implementing Agent**:
> You are working with an active third-party FOSS codebase. **Do NOT over-engineer or implement complex algorithmic relaxation upfront.** 
> Your first priority is empirical discovery against Graphify's real source code:
> 1. **Inspect Graphify's Actual Community Module**: How is Leiden currently called? Is it `leidenalg`, `cdlib`, NetworkX, or a lightweight custom heuristic?
> 2. **Start with Tier 1 (Frozen Baseline)**: First, get the AST parsing, Git diff hook, and graph edge splicing working under 500ms with a frozen baseline.
> 3. **Evaluate the Need for Tier 2**: Only add Bidirectional Consensus if PR diffs frequently break subsystem boundaries or if frozen baselines cause noticeable drift before mainline merges.
> 4. **Favor Simplicity**: If upstream Graphify already has caching primitives or graph export utilities, lean on them rather than inventing custom abstractions.

### Step-by-Step Execution Plan:
1. Clone `https://github.com/Graphify-Labs/graphify`.
2. Inspect the project layout (`pyproject.toml`, directory structure, tree-sitter bindings, graph representation).
3. Implement the SQLite/file-hash caching layer.
4. Add the `diff` subcommand leveraging `git diff`.
5. Implement Tier 1 community stability (frozen baseline with directory/neighbor inheritance for new files).
6. Verify incremental symbol splicing on a test repo with 1,000+ files.
7. Verify output schema compatibility with PACRE's `pacre-delta.json`.
8. Benchmark Tier 2 (Bidirectional Consensus) on complex refactoring PRs and document trade-offs.
