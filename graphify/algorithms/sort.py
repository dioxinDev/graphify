import networkx as nx
from typing import List

def get_topological_order(graph: nx.DiGraph) -> List[str]:
    """Get topological order for a given networkx directed graph."""
    if not isinstance(graph, nx.DiGraph):
        raise ValueError("Topological sort requires a directed graph (nx.DiGraph)")
    return list(nx.topological_sort(graph))
