#!/usr/bin/env python3
"""
wiki_graph_builder.py -- Build a knowledge graph from the Wiki's entities and concepts.

Usage:
    python3 wiki_graph_builder.py
    python3 wiki_graph_builder.py --force  # Rebuild even if graph exists
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ---------------------------------------------------------------------------
# Import helpers from wiki_core (shared module)
# ---------------------------------------------------------------------------
try:
    from wiki_core import (
        load_wiki_index,
        parse_frontmatter,
        resolve_wiki_root,
    )
except ImportError as exc:
    logging.error("Konnte wiki_core.py nicht importieren: %s", exc)
    sys.exit(1)

DEFAULT_WIKI_ROOT = resolve_wiki_root()


# ---------------------------------------------------------------------------
# Graph data structures
# ---------------------------------------------------------------------------
class WikiGraph:
    """Simple graph representation using adjacency lists."""
    
    def __init__(self):
        self.nodes: Dict[str, dict] = {}  # node_id -> {type, title, metadata, ...}
        self.edges: List[Tuple[str, str, str]] = []  # (from, to, relation)
        self.adjacency: Dict[str, List[Tuple[str, str]]] = {}  # node -> [(neighbor, relation)]
    
    def add_node(self, node_id: str, node_type: str, **metadata):
        if node_id not in self.nodes:
            self.nodes[node_id] = {"type": node_type, **metadata}
            self.adjacency[node_id] = []
    
    def add_edge(self, from_id: str, to_id: str, relation: str):
        if from_id in self.nodes and to_id in self.nodes:
            self.edges.append((from_id, to_id, relation))
            self.adjacency[from_id].append((to_id, relation))
            self.adjacency[to_id].append((from_id, relation))  # Undirected for traversal
    
    def neighbors(self, node_id: str) -> List[Tuple[str, str]]:
        return self.adjacency.get(node_id, [])
    
    def get_nodes_by_type(self, node_type: str) -> List[str]:
        return [nid for nid, meta in self.nodes.items() if meta.get("type") == node_type]
    
    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes,
            "edges": [{"from": f, "to": t, "relation": r} for f, t, r in self.edges],
            "meta": {
                "created": datetime.now().isoformat(),
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
            }
        }
    
    def save(self, path: Path):
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        logging.info("Graph saved: %s (%d nodes, %d edges)", path, len(self.nodes), len(self.edges))


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------
MARKDOWN_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')

def extract_links(content: str) -> List[Tuple[str, str]]:
    """Extract all markdown links and wikilinks from content."""
    links = []
    # Markdown links: [text](path)
    for match in MARKDOWN_LINK_RE.finditer(content):
        text, path = match.groups()
        links.append((text, path))
    # Wikilinks: [[text]]
    for match in WIKILINK_RE.finditer(content):
        text = match.group(1)
        links.append((text, text))
    return links


def resolve_link(path: str, current_file: Path, wiki_root: Path) -> str:
    """Resolve a relative link to a node_id."""
    if path.startswith("http://") or path.startswith("https://"):
        return None  # External link
    
    # Remove anchors
    path = path.split("#")[0]
    
    if not path or path == "/":
        return None
    
    # Relative to current file
    if path.startswith("../") or path.startswith("./"):
        target = (current_file.parent / path).resolve()
        try:
            rel = target.relative_to(wiki_root)
            return str(rel)
        except ValueError:
            return None
    
    # Absolute within wiki (may start with raw/, wiki/, etc.)
    target = wiki_root / path
    if target.exists():
        try:
            rel = target.relative_to(wiki_root)
            return str(rel)
        except ValueError:
            return None
    
    return None


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------
def build_wiki_graph(wiki_root: str, force: bool = False) -> WikiGraph:
    """Build knowledge graph from wiki entities, concepts, and raw files."""
    root = Path(wiki_root)
    graph_path = root / "wiki_graph.json"
    
    if graph_path.exists() and not force:
        logging.info("Graph exists at %s. Use --force to rebuild.", graph_path)
        # Load existing graph
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        G = WikiGraph()
        G.nodes = data["nodes"]
        for edge in data["edges"]:
            G.add_edge(edge["from"], edge["to"], edge["relation"])
        return G
    
    G = WikiGraph()
    
    # -----------------------------------------------------------------------
    # 1. Add all wiki files as document nodes
    # -----------------------------------------------------------------------
    search_dirs = [
        root / "raw",
        root / "wiki" / "entities",
        root / "wiki" / "concepts",
        root / "synthesis",
    ]
    
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for md_file in search_dir.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            
            rel_path = str(md_file.relative_to(root))
            try:
                raw = md_file.read_text(encoding="utf-8")
                meta, content = parse_frontmatter(raw)
            except Exception as exc:
                logging.warning("Could not parse %s: %s", rel_path, exc)
                continue
            
            node_type = "document"
            if "wiki/entities/" in rel_path:
                node_type = "entity"
            elif "wiki/concepts/" in rel_path:
                node_type = "concept"
            elif "synthesis/" in rel_path:
                node_type = "synthesis"
            elif "raw/" in rel_path:
                node_type = "source"
            
            G.add_node(
                rel_path,
                node_type,
                title=meta.get("title", md_file.stem),
                slug=meta.get("slug", ""),
                source_refs=meta.get("source_refs", []),
                confidence=meta.get("confidence", None),
            )
    
    logging.info("Added %d nodes", len(G.nodes))
    
    # -----------------------------------------------------------------------
    # 2. Extract links between documents
    # -----------------------------------------------------------------------
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for md_file in search_dir.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            
            rel_path = str(md_file.relative_to(root))
            try:
                raw = md_file.read_text(encoding="utf-8")
                meta, content = parse_frontmatter(raw)
            except Exception:
                continue
            
            links = extract_links(content)
            for text, path in links:
                target = resolve_link(path, md_file, root)
                if target and target in G.nodes:
                    # Determine relation type
                    relation = "links_to"
                    if "wiki/entities/" in target:
                        relation = "mentions_entity"
                    elif "wiki/concepts/" in target:
                        relation = "mentions_concept"
                    elif "raw/" in target:
                        relation = "cites_source"
                    elif "synthesis/" in target:
                        relation = "references_synthesis"
                    
                    G.add_edge(rel_path, target, relation)
    
    # -----------------------------------------------------------------------
    # 3. Connect source_refs
    # -----------------------------------------------------------------------
    for node_id, meta in G.nodes.items():
        source_refs = meta.get("source_refs", [])
        if isinstance(source_refs, list):
            for ref in source_refs:
                ref_path = str(root / ref)
                if ref in G.nodes:
                    G.add_edge(node_id, ref, "source_ref")
    
    logging.info("Added %d edges", len(G.edges))
    
    # -----------------------------------------------------------------------
    # 4. Save graph
    # -----------------------------------------------------------------------
    G.save(graph_path)
    
    return G


# ---------------------------------------------------------------------------
# Embedding index (Sentence Transformers)
# ---------------------------------------------------------------------------
def build_embedding_index(G: WikiGraph, wiki_root: Path, force: bool = False) -> Dict[str, List[float]]:
    """Build sentence embedding index for all nodes.
    
    Returns dict: node_id -> embedding vector
    """
    index_path = wiki_root / "wiki_embeddings.json"
    
    if not force and index_path.exists():
        logging.info("Loading existing embedding index...")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data.get("embeddings", {})
    
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logging.warning("sentence-transformers not installed, skipping embedding index")
        return {}
    
    logging.info("Building embedding index with all-MiniLM-L6-v2...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    embeddings = {}
    texts = []
    node_ids = []
    
    for node_id, meta in G.nodes.items():
        title = meta.get("title", "")
        if isinstance(title, list):
            title = " ".join(str(t) for t in title)
        title = str(title)
        
        # Combine title + first 500 chars of content for richer embeddings
        text = title
        file_path = wiki_root / node_id
        if file_path.exists():
            try:
                raw = file_path.read_text(encoding="utf-8")
                # Strip frontmatter
                if raw.startswith("---"):
                    parts = raw.split("---", 2)
                    if len(parts) >= 3:
                        content = parts[2].strip()
                    else:
                        content = raw
                else:
                    content = raw
                text += " " + content[:500]
            except Exception:
                pass
        
        texts.append(text)
        node_ids.append(node_id)
    
    # Batch encode (more efficient)
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_ids = node_ids[i:i+batch_size]
        batch_embeddings = model.encode(batch_texts, convert_to_numpy=True, show_progress_bar=False)
        
        for node_id, emb in zip(batch_ids, batch_embeddings):
            embeddings[node_id] = emb.tolist()
        
        if (i // batch_size) % 10 == 0:
            logging.info("  Embedded %d/%d nodes...", min(i + batch_size, len(texts)), len(texts))
    
    # Save index
    index_data = {
        "model": "all-MiniLM-L6-v2",
        "dimensions": 384,
        "node_count": len(embeddings),
        "embeddings": embeddings,
    }
    index_path.write_text(json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info("Embedding index saved: %d nodes, %d dimensions", len(embeddings), 384)
    
    return embeddings


# ---------------------------------------------------------------------------
# Community detection (Leiden algorithm)
# ---------------------------------------------------------------------------
def detect_communities_leiden(G: WikiGraph) -> Dict[str, List[str]]:
    """Leiden community detection using igraph + leidenalg.
    
    Returns communities as dict: {community_id -> [node_ids]}
    """
    try:
        import igraph as ig
        import leidenalg as la
    except ImportError:
        logging.warning("igraph/leidenalg not installed, falling back to connected components")
        return detect_communities_connected_components(G)
    
    # Build igraph from WikiGraph
    node_list = list(G.nodes.keys())
    node_index = {nid: i for i, nid in enumerate(node_list)}
    
    ig_graph = ig.Graph(directed=False)
    ig_graph.add_vertices(len(node_list))
    
    # Add edges (avoid duplicates since graph is undirected)
    edge_set = set()
    for edge in G.edges:
        from_id = edge[0]  # Tuple: (from, to, relation)
        to_id = edge[1]
        if from_id in node_index and to_id in node_index:
            # Store as sorted tuple to avoid duplicates
            edge_key = tuple(sorted([node_index[from_id], node_index[to_id]]))
            edge_set.add(edge_key)
    
    ig_graph.add_edges(list(edge_set))
    
    logging.info("igraph: %d vertices, %d edges", ig_graph.vcount(), ig_graph.ecount())
    
    # Run Leiden algorithm
    partition = la.find_partition(
        ig_graph,
        la.ModularityVertexPartition,
        n_iterations=10,
        seed=42,  # Reproducible
    )
    
    # Convert back to node IDs
    communities = {}
    for i, membership in enumerate(partition.membership):
        cid = f"community_{membership}"
        if cid not in communities:
            communities[cid] = []
        communities[cid].append(node_list[i])
    
    # Sort communities by size (descending)
    communities = dict(sorted(communities.items(), key=lambda x: len(x[1]), reverse=True))
    
    logging.info("Leiden found %d communities", len(communities))
    for cid, nodes in list(communities.items())[:5]:
        types = set(G.nodes[n].get("type", "unknown") for n in nodes if n in G.nodes)
        logging.info("  %s: %d nodes, types: %s", cid, len(nodes), types)
    
    return communities


def detect_communities_connected_components(G: WikiGraph) -> Dict[str, List[str]]:
    """Simple community detection by connected components (fallback)."""
    visited = set()
    communities = {}
    community_id = 0
    
    for node_id in G.nodes:
        if node_id in visited:
            continue
        
        # BFS to find connected component
        component = []
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor, _ in G.neighbors(current):
                if neighbor not in visited:
                    queue.append(neighbor)
        
        if len(component) > 1:  # Only communities with >1 node
            communities[f"community_{community_id}"] = component
            community_id += 1
    
    logging.info("Found %d communities (connected components)", len(communities))
    return communities


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build knowledge graph from Wiki")
    parser.add_argument("--wiki-root", default=DEFAULT_WIKI_ROOT)
    parser.add_argument("--force", action="store_true", help="Force rebuild even if graph exists")
    args = parser.parse_args()
    
    wiki_root = resolve_wiki_root(args.wiki_root).resolve()
    if not wiki_root.exists():
        logging.error("Wiki root does not exist: %s", wiki_root)
        sys.exit(1)
    
    G = build_wiki_graph(str(wiki_root), force=args.force)
    communities = detect_communities_leiden(G)
    embeddings = build_embedding_index(G, wiki_root, force=args.force)
    
    # Save community info
    community_path = wiki_root / "wiki_communities.json"
    community_data = {
        cid: {
            "nodes": nodes,
            "size": len(nodes),
            "types": list(set(G.nodes[n].get("type", "unknown") for n in nodes if n in G.nodes)),
        }
        for cid, nodes in communities.items()
    }
    community_path.write_text(json.dumps(community_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info("Communities saved: %s", community_path)


if __name__ == "__main__":
    main()
