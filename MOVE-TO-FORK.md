# MOVE-TO-FORK.md

This document outlines the algorithms currently in P-ACRE that must be migrated to our `Graphify` fork (`/vendor/graphify`).

## Migration Guidelines
- **Core Philosophy**: Generic graph algorithms belong in the engine (`Graphify`), while domain-specific architectural analysis belongs in P-ACRE.
- **Goal**: De-bloat P-ACRE and centralize engine-level capabilities.

---

## 1. PageRank (`src/engine/graph/pagerank.ts`)
- **Current Role**: Implements generic PageRank to compute module influence/criticality.
- **Migration Path**: 
  - Move the implementation to a new utility file in the Graphify fork (e.g., `graphify/algorithms/pagerank.py` or equivalent).
  - Expose a clean interface: `computePageRank(graph: Graph) -> Map<NodeId, Score>`.
  - P-ACRE will then import this via the existing Graphify adapter.

## 2. Topological Sort (`src/engine/graph/topological.ts`)
- **Current Role**: Orders the dependency graph to identify cyclic dependencies and build orders.
- **Migration Path**:
  - Move to Graphify fork (e.g., `graphify/algorithms/sort.py`).
  - Expose interface: `getTopologicalOrder(graph: Graph) -> NodeId[]`.
  - This allows Graphify to natively detect cycles, removing the need for P-ACRE to perform manual graph traversals.

---

## Post-Migration Checklist for P-ACRE
1. **Refactor Imports**: Update `src/engine/workflowOrchestrator.ts` and `src/engine/graph/subsystems.ts` to import these algorithms from the Graphify adapter service (`src/services/graphifyAdapter.ts`).
2. **Verify Interface**: Ensure the Graphify-exposed API matches the existing P-ACRE utility signatures to minimize refactoring impact.
3. **Delete**: Once verified, delete `src/engine/graph/pagerank.ts` and `src/engine/graph/topological.ts`.
