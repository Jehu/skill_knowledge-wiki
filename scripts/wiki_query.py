#!/usr/bin/env python3
"""
wiki_query_v2.py -- Graph-based Wiki Query Engine

Usage:
    python3 wiki_query_v2.py --question "Best Practices für das Schreiben von Skills"
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

# ---------------------------------------------------------------------------
# Config (from config.yaml in skill directory)
# ---------------------------------------------------------------------------
CONFIG_PATH = SKILL_DIR / "config.yaml"

try:
    import yaml
    CFG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
except Exception:
    CFG = {}

LLM_CFG = (CFG or {}).get("llm", {})
EMB_CFG = (CFG or {}).get("embeddings", {})

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
        inject_wikilinks,
        make_slug,
        UMLAUT_MAP as INGEST_UMLAUT_MAP,
        dump_frontmatter,
        parse_frontmatter,
        resolve_wiki_root,
    )
except ImportError as exc:
    logging.error("Konnte wiki_core.py nicht importieren: %s", exc)
    sys.exit(1)

DEFAULT_WIKI_ROOT = resolve_wiki_root()


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------
class WikiGraph:
    """Lightweight graph wrapper with community + embedding support."""
    
    def __init__(self, wiki_root: str):
        self.root = Path(wiki_root)
        self.graph_path = self.root / "wiki_graph.json"
        self.communities_path = self.root / "wiki_communities.json"
        self.embeddings_path = self.root / "wiki_embeddings.json"
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = []
        self.adjacency: Dict[str, List[Tuple[str, str]]] = {}
        self.communities: Dict[str, List[str]] = {}
        self.node_community: Dict[str, str] = {}
        self.embeddings: Dict[str, List[float]] = {}
        self.embedding_model: Optional[str] = None
        self._load()
    
    def _load(self):
        if not self.graph_path.exists():
            logging.error("Graph not found. Run wiki_graph_builder.py first.")
            sys.exit(1)
        
        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        self.nodes = data["nodes"]
        self.edges = data["edges"]
        
        # Build adjacency
        for edge in self.edges:
            from_id = edge["from"]
            to_id = edge["to"]
            relation = edge["relation"]
            if from_id not in self.adjacency:
                self.adjacency[from_id] = []
            if to_id not in self.adjacency:
                self.adjacency[to_id] = []
            self.adjacency[from_id].append((to_id, relation))
            self.adjacency[to_id].append((from_id, relation))
        
        # Load communities
        if self.communities_path.exists():
            comm_data = json.loads(self.communities_path.read_text(encoding="utf-8"))
            if "communities" in comm_data:
                self.communities = comm_data["communities"]
            else:
                self.communities = {
                    cid: info["nodes"] 
                    for cid, info in comm_data.items() 
                    if isinstance(info, dict) and "nodes" in info
                }
            for comm_id, node_list in self.communities.items():
                for node_id in node_list:
                    self.node_community[node_id] = comm_id
            logging.info("Loaded %d communities", len(self.communities))
        else:
            logging.warning("No communities file found.")
        
        # Load embeddings
        if self.embeddings_path.exists():
            emb_data = json.loads(self.embeddings_path.read_text(encoding="utf-8"))
            self.embeddings = emb_data.get("embeddings", {})
            self.embedding_model = emb_data.get("model", "unknown")
            logging.info("Loaded %d embeddings (%s)", len(self.embeddings), self.embedding_model)
        else:
            logging.warning("No embeddings file found. Run wiki_graph_builder.py --force to generate.")
    
    def neighbors(self, node_id: str, max_depth: int = 1) -> List[Tuple[str, str, int]]:
        """BFS to find neighbors up to max_depth. Returns (node_id, relation, depth)."""
        visited = {node_id: 0}
        queue = [(node_id, 0)]
        results = []
        
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            
            for neighbor, relation in self.adjacency.get(current, []):
                if neighbor not in visited:
                    visited[neighbor] = depth + 1
                    results.append((neighbor, relation, depth + 1))
                    queue.append((neighbor, depth + 1))
        
        return results
    
    def find_nodes_by_keyword(self, keyword: str) -> List[str]:
        """Find nodes whose title or content matches keyword."""
        keyword_lower = keyword.lower()
        matches = []
        for node_id, meta in self.nodes.items():
            title = meta.get("title", "")
            if isinstance(title, list):
                title = " ".join(str(t) for t in title)
            title = str(title).lower()
            if keyword_lower in title:
                matches.append(node_id)
        return matches


# ---------------------------------------------------------------------------
# Entity extraction from question
# ---------------------------------------------------------------------------
STOPWORDS = {
    "die", "der", "den", "das", "ein", "eine", "einer", "eines",
    "und", "oder", "aber", "sondern", "denn", "weil", "wenn", "als",
    "ist", "sind", "war", "waren", "wird", "werden", "wurde", "wurden",
    "hat", "haben", "hatte", "hatten", "kann", "können", "konnte", "konnten",
    "soll", "sollen", "sollte", "sollten", "muss", "müssen", "musste", "mussten",
    "für", "mit", "von", "zu", "bei", "nach", "aus", "an", "in", "im", "auf",
    "über", "unter", "vor", "hinter", "neben", "zwischen", "durch", "gegen",
    "wie", "was", "wer", "wo", "wann", "warum", "weshalb", "welche", "welcher",
    "welches", "wieso", "weswegen", "dafür", "dagegen", "dadurch", "deswegen",
}

def extract_keywords(question: str) -> List[str]:
    """Extract meaningful keywords from question."""
    words = re.findall(r'\b\w+\b', question.lower())
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return keywords


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_embedding_matches(graph: WikiGraph, question: str, top_k: int = 20) -> List[Tuple[str, float]]:
    """Find top-k similar nodes using sentence embeddings.
    
    Returns: [(node_id, similarity_score), ...]
    """
    if not graph.embeddings:
        return []
    
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logging.warning("sentence-transformers not installed, skipping embedding search")
        return []
    
    logging.info("Running embedding search for: '%s'", question)
    model = SentenceTransformer(EMB_CFG.get("model", "all-MiniLM-L6-v2"))
    query_emb = model.encode(question, convert_to_numpy=True)
    query_vec = query_emb.tolist()
    
    # Calculate similarities
    similarities = []
    for node_id, emb in graph.embeddings.items():
        sim = cosine_similarity(query_vec, emb)
        similarities.append((node_id, sim))
    
    # Sort by similarity (descending)
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    top_matches = similarities[:top_k]
    logging.info("Top embedding matches:")
    for node_id, sim in top_matches[:5]:
        title = graph.nodes.get(node_id, {}).get("title", node_id)
        logging.info("  - %.3f: %s", sim, title[:80])
    
    threshold = EMB_CFG.get("threshold", 0.5)
    top_matches = [(nid, sim) for nid, sim in top_matches if sim >= threshold]
    logging.info("After threshold (>=%.2f): %d matches", threshold, len(top_matches))
    
    return top_matches


def find_relevant_nodes(graph: WikiGraph, question: str, global_search: bool = True, embedding_search: bool = True) -> Dict[str, dict]:
    """Find relevant nodes using keyword matching + graph traversal + community global search + embedding synonym search.
    
    Args:
        graph: The WikiGraph instance
        question: User question
        global_search: If True, also include all nodes from communities of direct matches
        embedding_search: If True, also include top-k embedding-similar nodes
    """
    keywords = extract_keywords(question)
    logging.info("Keywords: %s", keywords)
    
    # Phase 1: Direct keyword matches (exclude existing synthesis files)
    direct_matches = set()
    for kw in keywords:
        matches = graph.find_nodes_by_keyword(kw)
        for m in matches:
            # Skip synthesis files to avoid self-referential citations
            if not m.startswith("synthesis/"):
                direct_matches.add(m)
    
    logging.info("Direct matches: %d (synthesis files excluded)", len(direct_matches))
    
    # Phase 2: Graph traversal (1-hop and 2-hop neighbors)
    expanded = {}
    for node_id in direct_matches:
        # Count how many query keywords appear in the node title (for priority sorting)
        title = str(graph.nodes[node_id].get("title", "")).lower()
        if isinstance(graph.nodes[node_id].get("title", ""), list):
            title = " ".join(str(t) for t in graph.nodes[node_id].get("title", []))
        title = title.lower()
        kw_hits = sum(1 for kw in keywords if kw in title)
        
        expanded[node_id] = {
            "match_type": "direct",
            "depth": 0,
            "relation": "keyword_match",
            "keyword_hits": kw_hits,
        }
        
        # 1-hop neighbors
        for neighbor, relation, depth in graph.neighbors(node_id, max_depth=1):
            if neighbor not in expanded:
                expanded[neighbor] = {
                    "match_type": "neighbor",
                    "depth": depth,
                    "relation": relation,
                    "via": node_id,
                }
        
        # 2-hop neighbors (only for high-value nodes)
        if graph.nodes[node_id].get("type") in ("concept", "entity"):
            for neighbor, relation, depth in graph.neighbors(node_id, max_depth=2):
                if neighbor not in expanded:
                    expanded[neighbor] = {
                        "match_type": "distant",
                        "depth": depth,
                        "relation": relation,
                        "via": node_id,
                    }
    
    # Phase 3: Community-based Global Search
    if global_search and graph.communities:
        communities_to_expand = set()
        for node_id in direct_matches:
            if node_id in graph.node_community:
                communities_to_expand.add(graph.node_community[node_id])
        
        logging.info("Expanding %d communities for global search", len(communities_to_expand))
        
        for comm_id in communities_to_expand:
            community_nodes = graph.communities.get(comm_id, [])
            for node_id in community_nodes:
                if node_id not in expanded:
                    expanded[node_id] = {
                        "match_type": "community",
                        "depth": 1,
                        "relation": f"community:{comm_id}",
                        "via": "global_search",
                    }
        
        logging.info("After community expansion: %d nodes", len(expanded))
    
    # Phase 4: Embedding-based Synonym Search
    if embedding_search and graph.embeddings:
        embedding_matches = find_embedding_matches(graph, question, top_k=20)
        
        for node_id, sim in embedding_matches:
            if node_id not in expanded:
                # Only add high-confidence embedding matches (>0.5 similarity)
                if sim > 0.5:
                    expanded[node_id] = {
                        "match_type": "embedding",
                        "depth": 1,  # Treat as depth 1 for priority
                        "relation": f"embedding:{sim:.3f}",
                        "via": "semantic_search",
                        "similarity": sim,
                    }
        
        logging.info("After embedding expansion: %d nodes", len(expanded))
    
    logging.info("Expanded matches: %d", len(expanded))
    return expanded


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------
def assemble_context(graph: WikiGraph, relevant_nodes: Dict[str, dict], max_tokens: int = 50000) -> List[dict]:
    """Assemble context from relevant nodes, respecting token limit.
    
    Priority order:
    1. Direct matches (keyword hits)
    2. Community nodes (thematically related via Leiden clustering)
    3. 1-hop neighbors (graph traversal)
    4. 2-hop neighbors (distant)
    """
    context = []
    token_estimate = 0
    
    # Sort by relevance: direct (by keyword_hits desc) > embedding > community > neighbor (depth 1) > distant (depth 2)
    sorted_nodes = sorted(
        relevant_nodes.items(),
        key=lambda x: (
            0 if x[1]["match_type"] == "direct" else
            1 if x[1]["match_type"] == "embedding" else
            2 if x[1]["match_type"] == "community" else
            3 if x[1]["depth"] == 1 else 4,
            -x[1].get("keyword_hits", 0),  # More keyword hits = higher priority
        )
    )
    
    for node_id, meta in sorted_nodes:
        if token_estimate >= max_tokens:
            break
        
        node_info = graph.nodes.get(node_id, {})
        node_type = node_info.get("type", "unknown")
        
        # Skip index files and backups
        if node_id.endswith("_index.md") or node_id.endswith(".bak"):
            continue
        
        # Load content
        file_path = graph.root / node_id
        if not file_path.exists():
            continue
        
        try:
            raw = file_path.read_text(encoding="utf-8")
            frontmatter, content = parse_frontmatter(raw)
        except Exception:
            continue
        
        # Determine content length based on node type and match_type
        if meta["match_type"] == "direct":
            max_chars = 4000  # Full content for direct matches
        elif meta["match_type"] == "embedding":
            max_chars = 3000  # Medium-long for embedding matches (semantically relevant)
        elif meta["match_type"] == "community":
            max_chars = 2500  # Medium-long for community nodes (thematically relevant)
        elif meta["depth"] == 1:
            max_chars = 2000  # Medium for 1-hop neighbors
        else:
            max_chars = 1000  # Short for distant neighbors
        
        # For source documents, include more content
        if node_type == "source" and meta["match_type"] == "direct":
            max_chars = 6000
        elif node_type == "source" and meta["match_type"] == "embedding":
            max_chars = 4000
        elif node_type == "source" and meta["match_type"] == "community":
            max_chars = 3500
        
        content_snippet = content[:max_chars]
        if len(content) > max_chars:
            content_snippet += "\n\n[...]"
        
        # Estimate tokens (rough: 4 chars ≈ 1 token)
        estimated_tokens = len(content_snippet) // 4
        
        if token_estimate + estimated_tokens > max_tokens:
            break
        
        token_estimate += estimated_tokens
        
        context.append({
            "node_id": node_id,
            "node_type": node_type,
            "title": node_info.get("title", node_id),
            "match_type": meta["match_type"],
            "depth": meta["depth"],
            "relation": meta.get("relation", ""),
            "content": content_snippet,
            "source_path": node_id,
        })
    
    logging.info("Assembled context: %d files, ~%d tokens", len(context), token_estimate)
    return context


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------
def generate_answer(question: str, context_files: List[dict]) -> Tuple[str, int, str, float]:
    """Generate answer via Ollama with confidence scoring.
    
    Returns: (answer, inferred_paragraphs, done_reason, confidence)
    """
    
    # Build context block
    context_parts = []
    for i, ctx in enumerate(context_files, 1):
        title = ctx["title"]
        node_type = ctx["node_type"]
        match_type = ctx["match_type"]
        depth = ctx["depth"]
        content = ctx["content"]
        source = ctx["source_path"]
        
        context_parts.append(
            f"--- Quelle {i}: {title} ({node_type}, {match_type}, depth={depth}) ---\n"
            f"Pfad: {source}\n"
            f"{content}"
        )
    
    context_block = "\n\n".join(context_parts)
    
    # Calculate base confidence from context quality
    direct_sources = sum(1 for c in context_files if c["match_type"] == "direct")
    neighbor_sources = sum(1 for c in context_files if c["match_type"] == "neighbor")
    total_sources = len(context_files)
    
    if total_sources == 0:
        base_confidence = 0.0
    elif direct_sources >= 3:
        base_confidence = 0.85
    elif direct_sources >= 1:
        base_confidence = 0.65
    elif neighbor_sources >= 3:
        base_confidence = 0.50
    else:
        base_confidence = 0.30
    
    prompt = (
        "Du bist ein Analyse-Assistent für ein persönliches Knowledge-Wiki.\n"
        "Deine Aufgabe: Beantworte die Frage präzise und faktenbasiert basierend "
        "auf den bereitgestellten Wiki-Einträgen.\n\n"
        "Regeln:\n"
        "- Antworte auf Deutsch.\n"
        "- Antworte so ausführlich wie nötig, um die Frage vollständig zu beantworten.\n"
        "- Nutze Bulletpoints oder nummerierte Listen wenn sie die Klarheit erhöhen.\n"
        "- Wenn die Quellen lückenhaft sind, sage das explizit und ergänze mit sinnvollen Schlussfolgerungen — aber markiere diese als inferiert.\n"
        "- WICHTIG: Jede Quellenangabe MUSS ein klickbarer Markdown-Link sein: `[Quelle: Titel](../relativer/pfad.md)`\n"
        "- Beispiel: `[Quelle: Claude Code Einführung](../raw/ai-agents/2026-04-28-claude-code.md)`\n"
        "- Der Link muss relativ zum `synthesis/`-Verzeichnis sein, also mit `../` beginnen.\n"
        "- KEINE einsamen Quellenangaben ohne vorherigen Inhalt.\n"
        "- NIE dich selbst zitieren (keine `synthesis/...` Links).\n"
        "- Inferierte Absätze (eigene Schlussfolgerungen ohne klare Quelle) bekommen KEINE Quellenangabe — schreibe stattdessen am Absatzanfang: '> **Inferiert:**'\n\n"
        f"Frage: {question}\n\n"
        f"Wiki-Einträge:\n{context_block}\n\n"
        "Antwort:"
    )
    
    # Check prompt size
    if len(prompt) > 100000:
        prompt = prompt[:100000] + "\n\n[... Kontext gekürzt ...]"
    
    try:
        ollama_host = LLM_CFG.get("host", "http://localhost:11434").rstrip("/")
        resp = requests.post(
            f"{ollama_host}/api/generate",
            json={
                "model": LLM_CFG.get("model", "gemma4:e4b"),
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": LLM_CFG.get("temperature", 0.3),
                    "num_predict": LLM_CFG.get("num_predict", 8192),
                    "num_ctx": LLM_CFG.get("num_ctx", 65536),
                },
            },
            timeout=LLM_CFG.get("timeout", 180),
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data.get("response", "").strip()
        done_reason = data.get("done_reason", "")
        
        # Count inferred paragraphs
        inferred = 0
        for para in answer.split("\n\n"):
            stripped = para.strip()
            is_inferred = stripped.startswith("> **Inferiert:**") or stripped.startswith(">**Inferiert:**")
            has_citation = "](" in para or "^[" in para
            if stripped and is_inferred:
                inferred += 1
            elif stripped and not has_citation and not stripped.startswith("#") and not is_inferred:
                # Uncited paragraph that's not a heading
                pass  # Could count as inferred too
        
        # Adjust confidence based on inference ratio
        total_paras = len([p for p in answer.split("\n\n") if p.strip() and not p.strip().startswith("#")])
        if total_paras > 0:
            inference_ratio = inferred / total_paras
            confidence = base_confidence * (1 - inference_ratio * 0.5)
        else:
            confidence = base_confidence
        
        return answer, min(inferred, 5), done_reason, round(confidence, 2)
    
    except requests.exceptions.ConnectionError:
        logging.warning("Ollama nicht erreichbar (localhost:11434)")
        return "Ollama ist nicht erreichbar. Bitte starte Ollama und versuche es erneut.", 0, "error", 0.0
    except Exception as exc:
        logging.error("Ollama-Fehler: %s", exc)
        return f"Fehler bei der Antwortgenerierung: {exc}", 0, "error", 0.0


# ---------------------------------------------------------------------------
# Save synthesis
# ---------------------------------------------------------------------------
def save_synthesis(
    wiki_root: str,
    question: str,
    answer: str,
    context_files: List[dict],
    inferred_paragraphs: int,
    done_reason: str,
    confidence: float,
) -> Path:
    """Save synthesis page with enhanced frontmatter."""
    root = Path(wiki_root)
    synthesis_dir = root / "synthesis"
    synthesis_dir.mkdir(exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Better slug
    slug_text = re.sub(
        r"\b(wie|was|wer|wo|warum|weshalb|welche|welcher|welches|und|oder|ist|sind|war|wurden|kann|können|hat|haben|wird|werden)\b",
        "", question, flags=re.IGNORECASE
    )
    slug_text = re.sub(r"[^\w\s]", "", slug_text)
    slug_text = slug_text.strip().lower()
    for char, repl in INGEST_UMLAUT_MAP.items():
        slug_text = slug_text.replace(char, repl)
    slug_text = re.sub(r"[\s_]+", "-", slug_text)
    slug_text = re.sub(r"-+", "-", slug_text)
    slug_text = slug_text.strip("-")
    parts = slug_text.split("-")
    if len(parts) > 8:
        slug_text = "-".join(parts[:8])
    
    filename = f"{today}-{slug_text}.md"
    synthesis_path = synthesis_dir / filename
    rel_path = f"synthesis/{filename}"
    
    # Only include actually cited sources (exclude synthesis files)
    cited_sources = [
        c["source_path"] for c in context_files 
        if c["match_type"] == "direct" and not c["source_path"].startswith("synthesis/")
    ]
    
    # Determine provenance state
    if confidence >= 0.8:
        provenance = "extracted"
    elif confidence >= 0.5:
        provenance = "merged"
    else:
        provenance = "inferred"
    
    meta = {
        "title": f"Antwort: {question}",
        "date": today,
        "type": "synthesis",
        "question": question,
        "source_refs": cited_sources[:10],
        "confidence": confidence,
        "provenance_state": provenance,
        "inferred_paragraphs": inferred_paragraphs,
    }
    if done_reason == "length":
        meta["truncated"] = True
        meta["note"] = "Antwort war zu lang für das Context-Window und wurde abgeschnitten"
    
    wiki_index = load_wiki_index(wiki_root)
    
    # Fix relative paths in citations
    # raw/ and wiki/ need ../ prefix (they are in parent dirs)
    # synthesis/ needs ./ prefix (same directory)
    fixed_answer = answer
    
    # Fix raw/ and wiki/ links
    fixed_answer = re.sub(
        r'\(((?:raw|wiki)/)',
        r'(../\1',
        fixed_answer,
    )
    
    # Also fix [Quelle: raw/...] and [Quelle: wiki/...] citation format
    fixed_answer = re.sub(
        r'\[Quelle: ((?:raw|wiki)/)',
        r'[Quelle: ../\1',
        fixed_answer,
    )
    
    # Fix synthesis/ links (same directory, so just ./)
    fixed_answer = re.sub(
        r'\(synthesis/',
        r'(./',
        fixed_answer,
    )
    
    # Also fix [Quelle: synthesis/...] format
    fixed_answer = re.sub(
        r'\[Quelle: synthesis/',
        r'[Quelle: ./',
        fixed_answer,
    )
    
    # Resolve bare filenames in [Quelle: ...] citations using context_files
    # Ollama sometimes generates just "2026-03-27-something.md" without directory
    basename_to_path = {}
    for cf in context_files:
        src = cf.get("source_path", "")
        if src and "/" in src:
            basename = src.rsplit("/", 1)[1]
            basename_to_path[basename] = src
    
    def resolve_bare_citation(match):
        cite_path = match.group(1)
        # Already has directory prefix — skip
        if cite_path.startswith(("../", "./", "raw/", "wiki/", "synthesis/")):
            return match.group(0)
        # Try to resolve bare filename
        if cite_path in basename_to_path:
            return f"[Quelle: ../{basename_to_path[cite_path]}]"
        return match.group(0)
    
    fixed_answer = re.sub(
        r'\[Quelle: ([^\]]+)\]',
        resolve_bare_citation,
        fixed_answer,
    )
    
    # Convert [Quelle: path] to clickable [Quelle](path) links
    # Only match citations where the content is just a path (no spaces, no descriptive text)
    # Descriptive citations like [Quelle: title text](../path) are already valid Markdown links
    fixed_answer = re.sub(
        r'\[Quelle: ([^\]\s]+)\]',
        r'[Quelle](\1)',
        fixed_answer,
    )
    
    # Prepend title heading to the body
    fixed_answer = f"# {question}\n\n{fixed_answer}"
    
    linked_answer = inject_wikilinks(fixed_answer, wiki_index, rel_path)
    
    synthesis_path.write_text(dump_frontmatter(meta, linked_answer), encoding="utf-8")
    logging.info("Saved synthesis: %s", synthesis_path)
    
    return synthesis_path


# ---------------------------------------------------------------------------
# Regenerate index
# ---------------------------------------------------------------------------
def regen_index(wiki_root: str):
    """Call regen_index.py from wiki-ingest."""
    candidates = [
        Path(wiki_root) / "regen_index.py",
        SCRIPTS_DIR / "regen_index.py",
    ]
    script = None
    for cand in candidates:
        if cand.exists():
            script = cand
            break
    if script is None:
        logging.warning("regen_index.py nicht gefunden, überspringe Index-Regeneration")
        return
    logging.info("Running index regeneration: %s", script)
    try:
        subprocess.run([sys.executable, str(script), str(wiki_root)], check=True)
    except subprocess.CalledProcessError as exc:
        logging.error("Index-Regeneration fehlgeschlagen: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Graph-based Wiki Query")
    parser.add_argument("--question", required=True, help="Die zu beantwortende Frage")
    parser.add_argument("--wiki-root", default=DEFAULT_WIKI_ROOT)
    parser.add_argument("--max-context-tokens", type=int, default=50000, help="Max tokens for context")
    args = parser.parse_args()
    
    wiki_root = resolve_wiki_root(args.wiki_root).resolve()
    if not wiki_root.exists():
        logging.error("Wiki root existiert nicht: %s", wiki_root)
        sys.exit(1)
    
    # Load graph
    logging.info("Lade Knowledge Graph...")
    graph = WikiGraph(str(wiki_root))
    logging.info("Graph geladen: %d nodes, %d edges", len(graph.nodes), len(graph.edges))
    
    # Find relevant nodes
    logging.info("Suche relevante Knoten für: %s", args.question)
    relevant = find_relevant_nodes(graph, args.question)
    
    if not relevant:
        print("Keine relevanten Knoten im Graph gefunden.")
        sys.exit(0)
    
    # Assemble context
    context = assemble_context(graph, relevant, max_tokens=args.max_context_tokens)
    
    if not context:
        print("Kein Kontext zusammengestellt.")
        sys.exit(0)
    
    logging.info("Top context sources:")
    for ctx in context[:5]:
        logging.info("  - [%s] %s (match=%s, depth=%d)", 
                     ctx["node_type"], ctx["title"], ctx["match_type"], ctx["depth"])
    
    print("\n" + "=" * 60)
    print(f"FRAGE: {args.question}")
    print("=" * 60 + "\n")
    
    # Generate answer
    answer, inferred, done_reason, confidence = generate_answer(args.question, context)
    print(answer)
    print()
    
    if not answer.strip():
        print("FEHLER: Ollama hat eine leere Antwort geliefert.")
        sys.exit(1)
    
    if done_reason == "length":
        print("\n[WARNUNG] Antwort wurde abgeschnitten.\n")
    
    print(f"\n[Confidence: {confidence}] [Inferred paragraphs: {inferred}]")
    
    # Save synthesis
    synthesis_path = save_synthesis(
        str(wiki_root),
        args.question,
        answer,
        context,
        inferred,
        done_reason,
        confidence,
    )
    
    regen_index(str(wiki_root))
    
    print(f"\nGespeichert: {synthesis_path}")


if __name__ == "__main__":
    main()
