import networkx as nx
from typing import Dict

def compute_pagerank(graph: nx.Graph) -> Dict[str, float]:
    """Compute PageRank for a given networkx graph."""
    return nx.pagerank(graph)
