"""Debug visualizations — only called when settings.debug is True.

Files written to settings.save_location:
  debug_pre_merge.html       — all pre-merge environments + leftovers combined
  debug_merge_env_N.html     — individual pre-merge environment N
  debug_post_merge.html      — all merged environments + leftovers combined
  debug_merged_env_N.html    — individual merged environment N

Color themes
────────────
Pre-merge environments use a coherent **greenish** palette so all parts of
the same environment family read as visually related:
  onto_1 interior  #f1f8e9  (lightest green)
  onto_2 interior  #dcedc8  (very light green)
  border1          #c5e1a5  (light green)
  border2          #aed581  (medium green)
  aligned nodes    #33691e  (very dark green — stands out clearly)
  alignment edges  #558b2f  (dark green, dashed)
  onto_1 leftover  #b0bec5  (blue-grey)
  onto_2 leftover  #78909c  (darker blue-grey)

Post-merge environments each get a unique colour from a rotating 12-colour
palette; leftovers keep the same blue-grey tones as above.
"""
from pathlib import Path

from pyvis.network import Network
from rdflib import Graph, URIRef

from llm_onto_merger.extract_environments.merge_environment import MergeEnvironment
from llm_onto_merger.logger import get_logger
from llm_onto_merger.ontology import local_name

log = get_logger(__name__)

# ── pre-merge: coherent greenish palette ─────────────────────────────────────
_PRE_ONTO1 = "#f1f8e9"       # lightest green  — onto_1 interior
_PRE_ONTO2 = "#dcedc8"       # very light green — onto_2 interior
_PRE_BORDER1 = "#c5e1a5"     # light green     — border1
_PRE_BORDER2 = "#aed581"     # medium green    — border2
_PRE_ALIGNED = "#33691e"     # very dark green — aligned nodes
_PRE_ALIGN_EDGE = "#558b2f"  # dark green edge for alignment links

# ── post-merge: cycling palette ───────────────────────────────────────────────
_POST_PALETTE = [
    "#ef9a9a", "#f48fb1", "#ce93d8", "#9fa8da",
    "#90caf9", "#80deea", "#80cbc4", "#a5d6a7",
    "#e6ee9c", "#ffe082", "#ffcc80", "#bcaaa4",
]

# ── leftovers ─────────────────────────────────────────────────────────────────
_LEFTOVER1 = "#b0bec5"   # blue-grey      — onto_1 leftovers
_LEFTOVER2 = "#78909c"   # darker blue-grey — onto_2 leftovers


# ── helpers ───────────────────────────────────────────────────────────────────

def _net() -> Network:
    n = Network(
        height="900px", width="100%", directed=True,
        notebook=False, bgcolor="#ffffff", font_color="#222222",
    )
    n.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=120)
    return n


def _add_graph_nodes(
    net: Network, graph: Graph, color: str, seen: set[str]
) -> None:
    for s, _, o in graph:
        for node in (s, o):
            uri = str(node)
            if isinstance(node, URIRef) and uri not in seen:
                net.add_node(uri, label=local_name(uri), color=color, title=uri)
                seen.add(uri)


def _add_graph_edges(net: Network, graph: Graph) -> None:
    for s, p, o in graph:
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            net.add_edge(
                str(s), str(o),
                label=local_name(p), title=str(p),
                color="#aaaaaa", arrows="to",
            )


def _add_env(net: Network, env: MergeEnvironment, seen: set[str]) -> None:
    border1 = {str(u) for u in env.border1}
    border2 = {str(u) for u in env.border2}
    aligned = {a.entity1 for a in env.alignments} | {a.entity2 for a in env.alignments}

    def _nodes(onto: Graph, base: str, border_col: str) -> None:
        for s, _, o in onto:
            for node in (s, o):
                uri = str(node)
                if not isinstance(node, URIRef) or uri in seen:
                    continue
                seen.add(uri)
                if uri in aligned:
                    color, bw = _PRE_ALIGNED, 3
                elif uri in border1:
                    color, bw = _PRE_BORDER1, 2
                elif uri in border2:
                    color, bw = _PRE_BORDER2, 2
                else:
                    color, bw = base, 1
                net.add_node(uri, label=local_name(uri), color=color, borderWidth=bw, title=uri)

    _nodes(env.onto_1, _PRE_ONTO1, _PRE_BORDER1)
    _nodes(env.onto_2, _PRE_ONTO2, _PRE_BORDER2)
    _add_graph_edges(net, env.onto_1)
    _add_graph_edges(net, env.onto_2)
    for al in env.alignments:
        net.add_edge(
            al.entity1, al.entity2,
            label=f"{al.measure:.2f}",
            title=f"alignment: {al.measure:.4f}",
            color=_PRE_ALIGN_EDGE, dashes=True, width=2,
        )


def _save(net: Network, path: Path) -> None:
    net.save_graph(str(path))
    log.info("[debug] saved %s", path.name)


# ── public API ────────────────────────────────────────────────────────────────

def save_pre_merge_debug(
    merge_environments: list[MergeEnvironment],
    leftover_1: Graph,
    leftover_2: Graph,
    out_dir: Path,
) -> None:
    """Write debug_pre_merge.html and debug_merge_env_N.html."""
    combined = _net()
    combined_seen: set[str] = set()

    for i, env in enumerate(merge_environments):
        _add_env(combined, env, combined_seen)

        single = _net()
        single_seen: set[str] = set()
        _add_env(single, env, single_seen)
        _save(single, out_dir / f"debug_merge_env_{i}.html")

    _add_graph_nodes(combined, leftover_1, _LEFTOVER1, combined_seen)
    _add_graph_nodes(combined, leftover_2, _LEFTOVER2, combined_seen)
    _add_graph_edges(combined, leftover_1)
    _add_graph_edges(combined, leftover_2)
    _save(combined, out_dir / "debug_pre_merge.html")


def save_post_merge_debug(
    merged_environments: list[Graph],
    leftover_1: Graph,
    leftover_2: Graph,
    out_dir: Path,
) -> None:
    """Write debug_post_merge.html and debug_merged_env_N.html."""
    combined = _net()
    combined_seen: set[str] = set()

    for i, graph in enumerate(merged_environments):
        color = _POST_PALETTE[i % len(_POST_PALETTE)]
        _add_graph_nodes(combined, graph, color, combined_seen)
        _add_graph_edges(combined, graph)

        single = _net()
        single_seen: set[str] = set()
        _add_graph_nodes(single, graph, color, single_seen)
        _add_graph_edges(single, graph)
        _save(single, out_dir / f"debug_merged_env_{i}.html")

    _add_graph_nodes(combined, leftover_1, _LEFTOVER1, combined_seen)
    _add_graph_nodes(combined, leftover_2, _LEFTOVER2, combined_seen)
    _add_graph_edges(combined, leftover_1)
    _add_graph_edges(combined, leftover_2)
    _save(combined, out_dir / "debug_post_merge.html")
