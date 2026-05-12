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
from collections import deque
from pathlib import Path

from pyvis.network import Network
from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..extract_environments.merge_environment import MergeEnvironment
from ..logger import get_logger
from ..ontology import local_name

log = get_logger(__name__)


def _restore_env_for_display(
    env: MergeEnvironment,
    reverse_map: dict[str, str],
) -> MergeEnvironment:
    """Return a display-only copy of env with onto_2 URIs restored to their
    original entity2 URIs (undoing the pre-rename done before extraction).
    onto_1 and border1 are shared by reference (not modified).
    """
    if not reverse_map:
        return env

    def _sub(uri: URIRef) -> URIRef:
        return URIRef(reverse_map[str(uri)]) if str(uri) in reverse_map else uri

    restored_onto2 = Graph()
    for s, p, o in env.onto_2:
        restored_onto2.add((
            _sub(s) if isinstance(s, URIRef) else s,
            p,
            _sub(o) if isinstance(o, URIRef) else o,
        ))

    restored_border2 = deque(_sub(u) for u in env.border2)

    restored_alignments = [
        al.model_copy(update={"entity2": reverse_map.get(al.entity2, al.entity2)})
        for al in env.alignments
    ]

    return MergeEnvironment(
        onto_1=env.onto_1,
        onto_2=restored_onto2,
        alignments=restored_alignments,
        border1=env.border1,
        border2=restored_border2,
    )


# ── pre-merge palette ────────────────────────────────────────────────────────
# onto_1 → blue family, onto_2 → orange family, aligned → red, edges → purple
_PRE_ONTO1      = "#e3f2fd"   # pale blue        — onto_1 interior nodes
_PRE_ONTO2      = "#fff3e0"   # pale orange      — onto_2 interior nodes
_PRE_BORDER1    = "#1565c0"   # strong blue      — border1 nodes
_PRE_BORDER2    = "#e65100"   # strong orange    — border2 nodes
_PRE_ALIGNED    = "#c62828"   # strong red       — aligned (seed) nodes
_PRE_ALIGN_EDGE = "#6a1b9a"   # purple dashed    — alignment edges

# ── post-merge: high-contrast cycling palette ────────────────────────────────
# All 12 colours are distinct from each other and from the two leftover colours.
_POST_PALETTE = [
    "#e53935",  # red
    "#8e24aa",  # purple
    "#1e88e5",  # blue
    "#00897b",  # teal
    "#f4511e",  # deep orange
    "#3949ab",  # indigo
    "#00acc1",  # cyan
    "#43a047",  # green
    "#fdd835",  # yellow
    "#fb8c00",  # amber
    "#6d4c41",  # brown
    "#f06292",  # pink
]

# ── leftovers ─────────────────────────────────────────────────────────────────
_LEFTOVER1 = "#cfd8dc"   # light blue-grey  — onto_1 leftovers
_LEFTOVER2 = "#455a64"   # dark slate       — onto_2 leftovers


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
    original_alignments: list[Alignment] | None = None,
) -> None:
    """Write debug_pre_merge.html and debug_merge_env_N.html.

    Pass original_alignments (before pre-rename) to restore entity2 URIs in
    onto_2 for visualization — otherwise '=' aligned nodes appear collapsed
    under entity1 URIs and the pre-merge view is misleading.
    """
    # Build entity1 → entity2 reverse map from '=' alignments so onto_2 nodes
    # are shown with their original URIs, not the pre-renamed entity1 URIs.
    reverse_map: dict[str, str] = {}
    if original_alignments:
        reverse_map = {
            al.entity1: al.entity2
            for al in original_alignments
            if al.relation == "=" and al.entity1 != al.entity2
        }

    combined = _net()
    combined_seen: set[str] = set()

    for i, env in enumerate(merge_environments):
        display_env = _restore_env_for_display(env, reverse_map)
        _add_env(combined, display_env, combined_seen)

        single = _net()
        single_seen: set[str] = set()
        _add_env(single, display_env, single_seen)
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
