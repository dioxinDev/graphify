"""Community detection on NetworkX graphs. Uses Leiden (graspologic) if available, falls back to Louvain (networkx). Splits oversized communities. Returns cohesion scores."""
from __future__ import annotations
import contextlib
import inspect
import io
import json
import sys
from pathlib import Path
try:
    import networkx as nx
except ImportError:
    nx = None


def _suppress_output():
    """Context manager to suppress stdout/stderr during library calls.

    graspologic's leiden() emits ANSI escape sequences (progress bars,
    colored warnings) that corrupt PowerShell 5.1's scroll buffer on
    Windows (see issue #19). Redirecting stdout/stderr to devnull during
    the call prevents this without losing any graphify output.
    """
    return contextlib.redirect_stdout(io.StringIO())


def _native_leiden(stable: nx.Graph, resolution: float) -> dict[str, int] | None:
    """Call graspologic_native.leiden() directly, bypassing graspologic's own
    package import.

    graspologic.partition.leiden() is a thin wrapper around exactly this
    native (Rust) call. Importing the *package* — as opposed to the native
    extension module it depends on — pulls in graspologic.layouts, which
    imports umap, which imports pynndescent, which numba-JIT-compiles at
    import time for a layout algorithm this function never calls: measured
    at 7-19s of one-time import cost against a ~1s native call and a ~1.4s
    full round trip (conversion + call + map-back) — see the "third update"
    in GRAPHIFY_BUILD_PERF.md for the measurements this is based on.

    Returns None (the caller falls through to the graspologic.partition.leiden
    path, then to the networkx Louvain fallback) if graspologic_native isn't
    installed, or if `stable` isn't the plain undirected, non-multigraph
    input leiden actually supports — the same shape check
    graspologic.partition.leiden itself makes before calling the same native
    function.
    """
    try:
        import graspologic_native as gn
    except ImportError:
        return None

    if stable.is_directed() or stable.is_multigraph():
        return None

    # graspologic_native identifies nodes by their string form; two DISTINCT
    # node objects that happen to stringify the same way would silently merge
    # under it (this is exactly what graspologic.partition.leiden's own
    # _IdentityMapper guards against). Graphify's own node IDs are already
    # unique strings by construction — extractors/resolution.py's
    # _disambiguate_colliding_node_ids salts any two distinct nodes that would
    # otherwise share a string id before the graph is ever built — so this is
    # a defensive check on an assumption that should never actually trip, not
    # an expected path. One pass over the nodes, cheaper than an
    # _IdentityMapper-style dict-store-per-edge-endpoint.
    id_to_node: dict[str, object] = {}
    for node in stable.nodes():
        key = str(node)
        existing = id_to_node.get(key)
        if existing is not None and existing != node:
            return None  # let graspologic.partition.leiden's own check handle/raise on this
        id_to_node[key] = node

    edges = [
        (str(u), str(v), float(attrs.get("weight", 1.0)))
        for u, v, attrs in stable.edges(data=True)
    ]

    try:
        old_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            with _suppress_output():
                _quality, native_partitions = gn.leiden(
                    edges=edges,
                    starting_communities=None,
                    resolution=resolution,
                    randomness=0.001,
                    iterations=1,
                    use_modularity=True,
                    seed=42,
                    trials=1,
                )
        finally:
            sys.stderr = old_stderr
    except Exception:
        return None

    partition = {
        id_to_node[node_id]: community
        for node_id, community in native_partitions.items()
    }
    next_community = max(partition.values(), default=-1) + 1
    for node in stable.nodes():
        if node not in partition:
            partition[node] = next_community
            next_community += 1
    return partition


def _partition(G: nx.Graph, resolution: float = 1.0) -> dict[str, int]:
    """Run community detection. Returns {node_id: community_id}.

    Tries Leiden (graspologic_native directly, then graspologic) first — best
    quality. Falls back to Louvain (built into networkx) if neither is
    installed.

    resolution > 1.0 → more, smaller communities.
    resolution < 1.0 → fewer, larger communities.

    Output from graspologic is suppressed to prevent ANSI escape codes
    from corrupting terminal scroll buffers on Windows PowerShell 5.1.
    """
    stable = nx.Graph()
    stable.add_nodes_from(sorted(G.nodes(), key=str))
    # Canonicalise the endpoint pair before sorting. On an undirected graph the
    # (u, v) orientation each edge is yielded with comes from adjacency
    # iteration, which follows CPython's per-process string-hash order - so the
    # SAME edge appears as (A, B) in one run and (B, A) in the next. Sorting on
    # the raw pair therefore does not canonicalise anything: the edge lands in a
    # different position, `stable` is built in a different insertion order, and
    # Louvain - order-sensitive even with a fixed seed - can return a different
    # grouping. Measured on a 914-node graph: identical input, identical
    # first-pass partition, but the cohesion-split pass produced 70 communities
    # under PYTHONHASHSEED=1 and 69 under =2. Sorting the pair itself removes
    # the dependency; for nx.Graph the orientation carries no meaning anyway.
    edge_rows = sorted(
        G.edges(data=True),
        key=lambda row: (
            *sorted((str(row[0]), str(row[1]))),
            json.dumps(row[2], sort_keys=True, ensure_ascii=False, default=str),
        ),
    )
    for src, tgt, attrs in edge_rows:
        stable.add_edge(src, tgt, **attrs)

    native_result = _native_leiden(stable, resolution)
    if native_result is not None:
        return native_result

    try:
        from graspologic.partition import leiden
        lsig = inspect.signature(leiden).parameters
        kwargs: dict = {}
        if "random_seed" in lsig:
            kwargs["random_seed"] = 42
        if "trials" in lsig:
            kwargs["trials"] = 1
        if "resolution" in lsig:
            kwargs["resolution"] = resolution
        # Suppress graspologic output to prevent ANSI escape codes from
        # corrupting PowerShell 5.1 scroll buffer (issue #19)
        old_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            with _suppress_output():
                result = leiden(stable, **kwargs)
        finally:
            sys.stderr = old_stderr
        return result
    except ImportError:
        pass

    # Fallback: networkx louvain (available since networkx 2.7).
    # Inspect kwargs to stay compatible across NetworkX versions — max_level
    # was added in a later release and prevents hangs on large sparse graphs.
    kwargs: dict = {"seed": 42, "threshold": 1e-4, "resolution": resolution}
    if "max_level" in inspect.signature(nx.community.louvain_communities).parameters:
        kwargs["max_level"] = 10
    communities = nx.community.louvain_communities(stable, **kwargs)
    return {node: cid for cid, nodes in enumerate(communities) for node in nodes}


_MAX_COMMUNITY_FRACTION = 0.25   # communities larger than 25% of graph get split
_MIN_SPLIT_SIZE = 10             # only split if community has at least this many nodes
_COHESION_SPLIT_THRESHOLD = 0.05 # re-split communities with cohesion below this
_COHESION_SPLIT_MIN_SIZE = 50    # only cohesion-split if community has at least this many nodes


def label_communities_by_hub(
    G: nx.Graph, communities: dict[int, list[str]]
) -> dict[int, str]:
    """Deterministic, LLM-free community labels: name each community after its
    highest-degree member — the structural hub — so a report reads ``auth`` /
    ``log_action`` instead of ``Community 70``. Degree is measured on the full graph
    ``G``; ties break by node id for run-to-run stability. A community whose members
    are all absent from ``G`` falls back to ``Community {cid}``.

    Used as the default (no-backend) labeler; an LLM naming pass, when configured,
    overrides these with richer names.
    """
    labels: dict[int, str] = {}
    for cid, members in communities.items():
        present = [n for n in members if n in G]
        if not present:
            labels[cid] = f"Community {cid}"
            continue
        # highest degree wins; ties broken by node id (ascending) for determinism
        hub = min(present, key=lambda n: (-G.degree(n), str(n)))
        name = str(G.nodes[hub].get("label") or hub).strip()
        if name.endswith("()"):
            name = name[:-2]
        labels[cid] = name or f"Community {cid}"
    return labels


def community_member_sigs(communities: dict[int, list[str]]) -> dict[int, str]:
    """Per-community membership fingerprints: ``{cid: sha256(sorted member ids)}``.

    Persisted next to ``.graphify_labels.json`` so a later ``cluster-only`` can tell
    which communities actually changed since labeling. A cid whose members no longer
    hash the same is a different community — reusing its old (LLM) label there is the
    "stale label after re-scoping" bug this guards against. Deterministic; independent
    of cid index, node order, and machine.
    """
    import hashlib

    sigs: dict[int, str] = {}
    for cid, members in communities.items():
        h = hashlib.sha256()
        for nid in sorted(str(n) for n in members):
            h.update(nid.encode("utf-8", "replace"))
            h.update(b"\x00")
        sigs[cid] = h.hexdigest()[:16]
    return sigs


def cluster(
    G: nx.Graph,
    resolution: float = 1.0,
    exclude_hubs_percentile: float | None = None,
) -> dict[int, list[str]]:
    """Run Leiden community detection. Returns {community_id: [node_ids]}.

    Community IDs are stable across runs: 0 = largest community after splitting.
    Oversized communities (> 25% of graph nodes, min 10) are split by running
    a second Leiden pass on the subgraph.

    Accepts directed or undirected graphs. DiGraphs are converted to undirected
    internally since Louvain/Leiden require undirected input.

    resolution: passed to Leiden/Louvain. >1.0 = more smaller communities,
        <1.0 = fewer larger communities. Default 1.0.
    exclude_hubs_percentile: if set (0-100), nodes whose degree exceeds this
        percentile are excluded from partitioning and reattached to their
        majority-vote neighbour community afterwards. Useful for staging/utility
        super-hubs that inflate god-node rankings (#919).
    """
    if G.number_of_nodes() == 0:
        return {}
    if G.is_directed():
        G = G.to_undirected()
    if G.number_of_edges() == 0:
        return {i: [n] for i, n in enumerate(sorted(G.nodes))}

    # Compute hub exclusion set before removing anything so degree is based on full graph
    hub_nodes: set[str] = set()
    if exclude_hubs_percentile is not None:
        degrees = sorted(d for _, d in G.degree())
        if degrees:
            idx = max(0, int(len(degrees) * exclude_hubs_percentile / 100) - 1)
            threshold = degrees[idx]
            hub_nodes = {n for n, d in G.degree() if d > threshold}

    # Leiden warns and drops isolates - handle them separately
    # Also exclude hub nodes from partitioning so they don't pull unrelated
    # subsystems into the same community
    excluded = hub_nodes
    isolates = [n for n in G.nodes() if G.degree(n) == 0 and n not in excluded]
    connected_nodes = [n for n in G.nodes() if G.degree(n) > 0 and n not in excluded]
    connected = G.subgraph(connected_nodes)

    raw: dict[int, list[str]] = {}
    if connected.number_of_nodes() > 0:
        partition = _partition(connected, resolution=resolution)
        for node, cid in partition.items():
            raw.setdefault(cid, []).append(node)

    # Each isolate becomes its own single-node community
    next_cid = max(raw.keys(), default=-1) + 1
    for node in isolates:
        raw[next_cid] = [node]
        next_cid += 1

    # Reattach excluded hubs by majority-vote neighbour community
    if hub_nodes:
        node_community: dict[str, int] = {n: cid for cid, nodes in raw.items() for n in nodes}
        for hub in sorted(hub_nodes):
            votes: dict[int, int] = {}
            for nb in G.neighbors(hub):
                cid = node_community.get(nb)
                if cid is not None:
                    votes[cid] = votes.get(cid, 0) + 1
            if votes:
                best = min(votes, key=lambda c: (-votes[c], c))
                raw.setdefault(best, []).append(hub)
                node_community[hub] = best
            else:
                raw[next_cid] = [hub]
                node_community[hub] = next_cid
                next_cid += 1

    # Split oversized communities
    max_size = max(_MIN_SPLIT_SIZE, int(G.number_of_nodes() * _MAX_COMMUNITY_FRACTION))
    final_communities: list[list[str]] = []
    for nodes in raw.values():
        if len(nodes) > max_size:
            final_communities.extend(_split_community(G, nodes))
        else:
            final_communities.append(nodes)

    # Second pass: re-split low-cohesion communities caused by doc-hub nodes
    # that bridge otherwise-unrelated subsystems (e.g. CLAUDE.md connected to everything).
    second_pass: list[list[str]] = []
    for nodes in final_communities:
        if len(nodes) >= _COHESION_SPLIT_MIN_SIZE and cohesion_score(G, nodes) < _COHESION_SPLIT_THRESHOLD:
            splits = _split_community(G, nodes)
            second_pass.extend(splits if len(splits) > 1 else [nodes])
        else:
            second_pass.append(nodes)
    final_communities = second_pass

    # Re-index by size descending. The tuple(sorted(nodes)) tiebreak makes this a
    # TOTAL order, so an identical grouping always gets identical community IDs.
    # Without it, the hundreds of equal-sized small communities are ordered by the
    # partitioner's (not seed-stable) enumeration order, so their integer IDs
    # permute run-to-run - which reads as massive "community churn" in a per-node
    # cid diff even though the actual grouping is reproducible (#1090 follow-up).
    final_communities.sort(key=lambda nodes: (-len(nodes), tuple(sorted(map(str, nodes)))))
    return {i: sorted(nodes) for i, nodes in enumerate(final_communities)}


def _split_community(G: nx.Graph, nodes: list[str]) -> list[list[str]]:
    """Run a second Leiden pass on a community subgraph to split it further."""
    subgraph = G.subgraph(nodes)
    if subgraph.number_of_edges() == 0:
        # No edges - split into individual nodes
        return [[n] for n in sorted(nodes)]
    try:
        sub_partition = _partition(subgraph)
        sub_communities: dict[int, list[str]] = {}
        for node, cid in sub_partition.items():
            sub_communities.setdefault(cid, []).append(node)
        if len(sub_communities) <= 1:
            return [sorted(nodes)]
        return [sorted(v) for v in sub_communities.values()]
    except Exception:
        return [sorted(nodes)]


def cohesion_score(G: nx.Graph, community_nodes: list[str]) -> float:
    """Ratio of actual intra-community edges to maximum possible."""
    n = len(community_nodes)
    if n <= 1:
        return 1.0
    subgraph = G.subgraph(community_nodes)
    # Exclude self-loops. ``build_from_json`` deliberately keeps recursive
    # ``calls`` self-edges ("real program structure rather than
    # import-resolution artifacts"), but ``possible`` below counts distinct
    # node PAIRS only, so a self-loop adds to the numerator without adding to
    # the denominator and pushes the ratio past 1.0 -- a two-node community
    # holding one recursive function scores 2.0. Drop them so numerator and
    # denominator measure the same thing.
    actual = subgraph.number_of_edges() - nx.number_of_selfloops(subgraph)
    possible = n * (n - 1) / 2
    return actual / possible if possible > 0 else 0.0


def score_all(G: nx.Graph, communities: dict[int, list[str]]) -> dict[int, float]:
    return {cid: cohesion_score(G, nodes) for cid, nodes in communities.items()}


def remap_communities_to_previous(
    communities: dict[int, list[str]],
    previous_node_community: dict[str, int],
) -> dict[int, list[str]]:
    """Remap community IDs to maximize overlap with a previous assignment.

    Uses greedy one-to-one matching by intersection size, then assigns fresh IDs
    to unmatched communities in deterministic order (size desc, lexical tie-break).
    """
    if not communities:
        return {}

    new_sets = {cid: set(nodes) for cid, nodes in communities.items()}
    old_sets: dict[int, set[str]] = {}
    for node, old_cid in previous_node_community.items():
        old_sets.setdefault(old_cid, set()).add(node)

    overlaps: list[tuple[int, int, int]] = []
    for old_cid, old_nodes in old_sets.items():
        for new_cid, new_nodes in new_sets.items():
            overlap = len(old_nodes & new_nodes)
            if overlap > 0:
                overlaps.append((overlap, old_cid, new_cid))
    overlaps.sort(key=lambda x: (-x[0], x[1], x[2]))

    new_to_final: dict[int, int] = {}
    used_old_ids: set[int] = set()
    matched_new_ids: set[int] = set()
    for _overlap, old_cid, new_cid in overlaps:
        if old_cid in used_old_ids or new_cid in matched_new_ids:
            continue
        new_to_final[new_cid] = old_cid
        used_old_ids.add(old_cid)
        matched_new_ids.add(new_cid)

    unmatched = [cid for cid in communities if cid not in matched_new_ids]
    unmatched.sort(key=lambda cid: (-len(communities[cid]), tuple(sorted(communities[cid]))))
    next_id = 0
    for new_cid in unmatched:
        while next_id in used_old_ids:
            next_id += 1
        new_to_final[new_cid] = next_id
        used_old_ids.add(next_id)
        next_id += 1

    remapped: dict[int, list[str]] = {}
    for new_cid, nodes in communities.items():
        remapped[new_to_final[new_cid]] = sorted(nodes)
    return dict(sorted(remapped.items(), key=lambda kv: kv[0]))


def bidirectional_consensus_relaxation(
    graph_data: dict,
    touched_source_files: set[str] | list[str],
    *,
    inertia: float = 0.05,
    resolution: float = 1.0,
) -> tuple[dict, list[dict[str, any]]]:
    """Bidirectional Consensus Local Relaxation for incremental community detection (PACRE Tier 2).

    Guarantees 100% bit-exact determinism:
    1. Bounds perturbation strictly to P = TouchedFiles ∪ DirectNeighbors(TouchedFiles).
    2. Performs Pass 1 (A->Z) and Pass 2 (Z->A) modularity sweeps with an inertia threshold.
    3. Commits migrations only when both passes agree (C_fwd == C_rev).
    4. Freezes order-sensitive conflicts (C_fwd != C_rev) to baseline and records borderAmbiguities.
    """
    if not graph_data or not graph_data.get("nodes"):
        return graph_data, []

    nodes_list = graph_data.get("nodes", [])
    nodes_by_id = {str(n.get("id")): n for n in nodes_list if n.get("id")}
    edges_list = graph_data.get("edges") or graph_data.get("links") or []

    # 1. Build adjacency and degree maps
    adj: dict[str, dict[str, float]] = {nid: {} for nid in nodes_by_id}
    degree: dict[str, float] = {nid: 0.0 for nid in nodes_by_id}
    total_m: float = 0.0

    for edge in edges_list:
        u = str(edge.get("source", ""))
        v = str(edge.get("target", ""))
        if u in nodes_by_id and v in nodes_by_id and u != v:
            w = float(edge.get("weight", 1.0))
            adj[u][v] = adj[u].get(v, 0.0) + w
            adj[v][u] = adj[v].get(u, 0.0) + w
            degree[u] += w
            degree[v] += w
            total_m += w

    if total_m <= 0:
        total_m = max(1.0, float(len(nodes_by_id)))

    # 2. Extract baseline community metadata and labels
    cid_to_name: dict[int, str] = {}
    node_to_base_cid: dict[str, int] = {}
    max_cid = -1

    for nid, node in nodes_by_id.items():
        raw_cid = node.get("community")
        cname = node.get("community_name")
        if raw_cid is not None:
            try:
                cid = int(raw_cid)
                node_to_base_cid[nid] = cid
                if cid > max_cid:
                    max_cid = cid
                if cname and cid not in cid_to_name:
                    cid_to_name[cid] = str(cname)
            except (ValueError, TypeError):
                pass

    # Directory map for sibling fallback
    dir_to_cids: dict[str, list[int]] = {}
    for nid, node in nodes_by_id.items():
        cid = node_to_base_cid.get(nid)
        s_file = node.get("source_file") or node.get("file")
        if cid is not None and s_file:
            parent_dir = str(Path(s_file).parent)
            dir_to_cids.setdefault(parent_dir, []).append(cid)

    # Assign initial community to nodes that lack one (newly added nodes)
    initial_comm: dict[str, int] = {}
    for nid, node in nodes_by_id.items():
        if nid in node_to_base_cid:
            initial_comm[nid] = node_to_base_cid[nid]
        else:
            # Neighbor majority
            neighbor_cids: dict[int, float] = {}
            for neighbor, weight in adj.get(nid, {}).items():
                ncid = node_to_base_cid.get(neighbor)
                if ncid is not None:
                    neighbor_cids[ncid] = neighbor_cids.get(ncid, 0.0) + weight
            if neighbor_cids:
                best_ncid = max(sorted(neighbor_cids.keys()), key=lambda c: neighbor_cids[c])
                initial_comm[nid] = best_ncid
            else:
                # Directory sibling majority
                s_file = node.get("source_file") or node.get("file")
                parent_dir = str(Path(s_file).parent) if s_file else ""
                dir_cids = dir_to_cids.get(parent_dir, [])
                if dir_cids:
                    from collections import Counter
                    best_dir_cid = Counter(dir_cids).most_common(1)[0][0]
                    initial_comm[nid] = best_dir_cid
                else:
                    max_cid += 1
                    initial_comm[nid] = max_cid
                    cid_to_name[max_cid] = f"Subsystem_{max_cid}"

    # 3. Identify Perturbation Boundary P = TouchedFiles ∪ DirectNeighbors(TouchedFiles)
    touched_normalized = {
        str(Path(p)).replace("\\", "/") for p in touched_source_files
    }
    touched_nodes: set[str] = set()
    for nid, node in nodes_by_id.items():
        s_file = node.get("source_file") or node.get("file")
        if s_file and str(Path(s_file)).replace("\\", "/") in touched_normalized:
            touched_nodes.add(nid)

    if not touched_nodes:
        # Fallback: if filenames didn't match directly, search suffix match
        for nid, node in nodes_by_id.items():
            s_file = str(node.get("source_file") or node.get("file") or "").replace("\\", "/")
            if any(s_file.endswith(tp) or tp.endswith(s_file) for tp in touched_normalized):
                touched_nodes.add(nid)

    perturbation_set: set[str] = set(touched_nodes)
    for tn in touched_nodes:
        for neighbor in adj.get(tn, {}):
            perturbation_set.add(neighbor)

    # If no nodes in perturbation set, return unchanged
    if not perturbation_set:
        return graph_data, []

    # Calculate community sigma (total degree per community)
    def _compute_sigma_tot(assignments: dict[str, int]) -> dict[int, float]:
        sigma: dict[int, float] = {}
        for nid, cid in assignments.items():
            sigma[cid] = sigma.get(cid, 0.0) + degree.get(nid, 0.0)
        return sigma

    # Helper to evaluate delta Q for moving node u to community target_c
    two_m = 2.0 * total_m
    two_m_sq = two_m * two_m

    def _calc_delta_q(u: str, target_c: int, sigma_tot: dict[int, float], curr_c: int, assignments: dict[str, int]) -> float:
        # Degree of u
        k_u = degree.get(u, 0.0)
        if k_u == 0:
            return 0.0
        # Edge weight to target_c
        k_u_c = sum(weight for v, weight in adj.get(u, {}).items() if assignments.get(v) == target_c and v != u)
        s_tot = sigma_tot.get(target_c, 0.0)
        if target_c == curr_c:
            s_tot -= k_u
        # Ratio of connections to target_c balanced by relative community mass
        affinity = k_u_c / k_u
        penalty = resolution * (s_tot / two_m)
        return affinity - (0.5 * penalty)

    # 4. Pass 1: Forward Sweep (Lexicographical order A -> Z)
    p_fwd = sorted(perturbation_set)
    comm_fwd = dict(initial_comm)
    sigma_fwd = _compute_sigma_tot(comm_fwd)

    for u in p_fwd:
        curr_c = comm_fwd[u]
        base_c = node_to_base_cid.get(u, curr_c)
        k_u = degree.get(u, 0.0)

        # Candidate communities: current, baseline, and all neighbor communities
        candidate_cids = {curr_c, base_c}
        for v in adj.get(u, {}):
            candidate_cids.add(comm_fwd[v])

        best_c = curr_c
        best_dq = _calc_delta_q(u, curr_c, sigma_fwd, curr_c, comm_fwd)
        base_dq = _calc_delta_q(u, base_c, sigma_fwd, curr_c, comm_fwd)

        for cand in sorted(candidate_cids):
            dq = _calc_delta_q(u, cand, sigma_fwd, curr_c, comm_fwd)
            if dq > best_dq:
                best_dq = dq
                best_c = cand

        # Apply inertia threshold relative to baseline
        if best_c != base_c:
            if (best_dq - base_dq) > inertia:
                comm_fwd[u] = best_c
                sigma_fwd[curr_c] -= k_u
                sigma_fwd[best_c] = sigma_fwd.get(best_c, 0.0) + k_u
            else:
                comm_fwd[u] = base_c
                if base_c != curr_c:
                    sigma_fwd[curr_c] -= k_u
                    sigma_fwd[base_c] = sigma_fwd.get(base_c, 0.0) + k_u

    # 5. Pass 2: Reverse Sweep (Reverse Lexicographical order Z -> A)
    p_rev = sorted(perturbation_set, reverse=True)
    comm_rev = dict(initial_comm)
    sigma_rev = _compute_sigma_tot(comm_rev)

    for u in p_rev:
        curr_c = comm_rev[u]
        base_c = node_to_base_cid.get(u, curr_c)
        k_u = degree.get(u, 0.0)

        candidate_cids = {curr_c, base_c}
        for v in adj.get(u, {}):
            candidate_cids.add(comm_rev[v])

        best_c = curr_c
        best_dq = _calc_delta_q(u, curr_c, sigma_rev, curr_c, comm_rev)
        base_dq = _calc_delta_q(u, base_c, sigma_rev, curr_c, comm_rev)

        for cand in sorted(candidate_cids, reverse=True):
            dq = _calc_delta_q(u, cand, sigma_rev, curr_c, comm_rev)
            if dq > best_dq:
                best_dq = dq
                best_c = cand

        if best_c != base_c:
            if (best_dq - base_dq) > inertia:
                comm_rev[u] = best_c
                sigma_rev[curr_c] -= k_u
                sigma_rev[best_c] = sigma_rev.get(best_c, 0.0) + k_u
            else:
                comm_rev[u] = base_c
                if base_c != curr_c:
                    sigma_rev[curr_c] -= k_u
                    sigma_rev[base_c] = sigma_rev.get(base_c, 0.0) + k_u

    # 6. Consensus Phase
    border_ambiguities: list[dict[str, any]] = []

    for u in sorted(perturbation_set):
        c_fwd = comm_fwd[u]
        c_rev = comm_rev[u]
        base_c = node_to_base_cid.get(u)

        if c_fwd == c_rev:
            final_c = c_fwd
        else:
            # Order-sensitive disagreement: retain baseline, report ambiguity
            final_c = base_c if base_c is not None else c_fwd
            border_ambiguities.append({
                "id": u,
                "baselineSubsystem": cid_to_name.get(base_c, f"Community {base_c}") if base_c is not None else None,
                "forwardCandidate": cid_to_name.get(c_fwd, f"Community {c_fwd}"),
                "reverseCandidate": cid_to_name.get(c_rev, f"Community {c_rev}"),
            })

        node = nodes_by_id[u]
        node["community"] = final_c
        node["community_name"] = cid_to_name.get(final_c, f"Community {final_c}")

    # Also update any new node in G outside perturbation_set (if any)
    for nid, node in nodes_by_id.items():
        if nid not in perturbation_set and "community" not in node:
            final_c = initial_comm[nid]
            node["community"] = final_c
            node["community_name"] = cid_to_name.get(final_c, f"Community {final_c}")

    return graph_data, border_ambiguities

