#!/usr/bin/env python3
"""
Compute ontology quality metrics based on 7 academic quality dimensions.

Metrics are derived from the Ewaluacja sections of each dimension:
  1. Structural Coherence          — ARC, unsatisfiable_classes, cycle_count
  2. Domain Coherence              — (case study only; no automated metric)
  3. Conciseness                   — syntactic_uniqueness_ratio, ALC
  4. Knowledge Completeness        — cross_onto_relations_count
  5. Hierarchy Integration Quality — cross_onto_subclassof_count, connectivity_ratio,
                                     average_depth, max_depth, average_breadth, max_breadth, ARC
  6. Accuracy                      — triple_preservation_ratio
  7. Understandability             — annotation_coverage_ratio

Usage:
    python tests/metrics_def.py <folder_name>

Reads:
    tests/inputs/<folder_name>/*.owl
    tests/outputs/<folder_name>/merged_ontology.owl
    tests/outputs/<folder_name>/applied_alignments.owl  (optional)

Writes:
    tests/outputs/<folder_name>/metrics_def.csv
    tests/outputs/<folder_name>/metrics_def.html
"""

import argparse
import csv
import sys
from collections import defaultdict, deque
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, URIRef

_OWL_DISJOINT_WITH = OWL.disjointWith
_OWL_CLASS = OWL.Class
_OWL_OBJ = OWL.ObjectProperty
_OWL_DATA = OWL.DatatypeProperty
_OWL_ANN = OWL.AnnotationProperty
_OWL_FP = OWL.FunctionalProperty
_OWL_IFP = OWL.InverseFunctionalProperty
_OWL_THING = OWL.Thing
_SUB = RDFS.subClassOf
_LABEL = RDFS.label
_COMMENT = RDFS.comment
_PROP_TYPES = (_OWL_OBJ, _OWL_DATA, _OWL_ANN, _OWL_FP, _OWL_IFP)

# Category name → (css-abbreviation, badge-colour)
_CATEGORIES: dict[str, tuple[str, str]] = {
    "Structural Coherence": ("sc", "#c0392b"),
    "Domain Coherence": ("dc", "#8e44ad"),
    "Conciseness": ("cn", "#16a085"),
    "Knowledge Completeness": ("kc", "#27ae60"),
    "Hierarchy Integration Quality": ("hi", "#2980b9"),
    "Accuracy": ("ac", "#d35400"),
    "Understandability": ("un", "#7f8c8d"),
}

# ── Metric registry ────────────────────────────────────────────────────────────
_REGISTRY: dict[str, dict] = {
    # ── Structural Coherence ───────────────────────────────────────────────────
    "ARC": {
        "source": "self-implemented",
        "categories": ["Structural Coherence", "Hierarchy Integration Quality"],
        "target": "low (ideally 1)",
        "interpretation": (
            "Absolute Root Cardinality — liczba klas bez nazwanego rodzica (korzeni hierarchii). "
            "Wartość 1 = spójna hierarchia z jednym korzeniem, brak orphan classes. "
            "Wymiar SC: każda klasa niebędąca korzeniem powinna mieć nazwaną nadklasę. "
            "Wymiar HIQ: ARC maleje gdy klasy-korzenie z obu ontologii zostają powiązane "
            "przez cross-ontology is-a lub zgrupowane pod wspólnym przodkiem."
        ),
    },
    "unsatisfiable_classes": {
        "source": "hermit_reasoner",
        "categories": ["Structural Coherence"],
        "target": "= 0",
        "interpretation": (
            "Liczba klas inferowanych przez HermiT jako równoważne owl:Nothing — klas "
            "niemożliwych do instancjonowania bez logicznej sprzeczności. Docelowo = 0. "
            "Główna miara Structural Coherence: 'An ontology is consistent if its axioms "
            "do not lead to logical contradictions' (Jiménez-Ruiz & Cuenca Grau, 2011). "
            "Wymaga: owlready2 + Java."
        ),
    },
    "cycle_count": {
        "source": "self-implemented",
        "categories": ["Structural Coherence"],
        "target": "= 0",
        "interpretation": (
            "Liczba cykli (back edges) w grafie skierowanym relacji subClassOf, "
            "wykrytych przez iteracyjny DFS. Docelowo = 0 — hierarchia klas powinna "
            "być acyklicznym grafem skierowanym (DAG) zakotwiczonym w owl:Thing. "
            "Cykl is-a (A ⊑ B ⊑ A) jest semantyczną sprzecznością."
        ),
    },
    # ── Conciseness ───────────────────────────────────────────────────────────
    "syntactic_uniqueness_ratio": {
        "source": "self-implemented",
        "categories": ["Conciseness"],
        "target": "= 1.0",
        "interpretation": (
            "Syntactic Uniqueness Ratio = liczba unikalnych nazw lokalnych klas / "
            "całkowita liczba URI klas. Wartość < 1.0 = duplikaty nazw pod różnymi "
            "namespace'ami (np. onto1:Person i onto2:Person jako osobne klasy). "
            "Docelowo = 1.0: żadne dwie klasy nie mają tej samej nazwy lokalnej."
        ),
    },
    "ALC": {
        "source": "self-implemented",
        "categories": ["Conciseness", "Hierarchy Integration Quality"],
        "target": "context-dependent",
        "interpretation": (
            "Absolute Leaf Cardinality — liczba klas bez podklas (liści). "
            "Wymiar C: spada po merge = mniej duplikatów liści = lepsza deduplication; "
            "interpretować razem z triple_preservation_ratio (zbyt duży spadek = utrata wiedzy). "
            "Wymiar HIQ: po dodaniu cross-ontology is-a część liści staje się węzłami pośrednimi."
        ),
    },
    # ── Knowledge Completeness ────────────────────────────────────────────────
    "cross_onto_relations_count": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "Liczba wszystkich relacji RDF (dowolny predykat) łączących encje z Onto1 "
            "z encjami z Onto2 w scalonej ontologii. Dla naiwnej unii = 0. "
            "Wzrost po merge = nowa wiedza emergentna — fakty nieobecne w żadnym źródle "
            "osobno, powstałe przez połączenie obu ontologii."
        ),
    },
    "new_intra_onto_relations_count": {
        "source": "self-implemented",
        "categories": ["Knowledge Completeness"],
        "target": "context-dependent",
        "interpretation": (
            "Liczba nowych relacji RDF (dowolny predykat) łączących dwie encje z TEJ SAMEJ "
            "ontologii źródłowej (Onto1↔Onto1 lub Onto2↔Onto2), nieobecnych w unii wejściowej. "
            "Wysoka wartość może wskazywać na uwidocznienie implicit relacji domenowych "
            "— model scalający sprawia, że stają się explicit. "
            "Niska wartość sugeruje, że model głównie łączył ontologie, bez uzupełniania "
            "wiedzy wewnątrz każdej z nich."
        ),
    },
    # ── Hierarchy Integration Quality ─────────────────────────────────────────
    "cross_onto_subclassof_count": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality", "Knowledge Completeness"],
        "target": "high",
        "interpretation": (
            "Liczba relacji SubClassOf łączących klasę z Onto1 z klasą z Onto2 "
            "(lub odwrotnie) w scalonej ontologii. Dla naiwnej unii = 0. "
            "Wyższy wynik = silniejsze zszycie hierarchii obu ontologii. "
            "Per He et al. (2022): bez cross-ontology is-a ~58% klas jest odłączonych "
            "od reszty hierarchii."
        ),
    },
    "connectivity_ratio": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "= 1.0",
        "interpretation": (
            "Connectivity Ratio = liczba klas osiągalnych z owl:Thing przez relacje "
            "SubClassOf / całkowita liczba klas. "
            "He et al. (2022) raportują ~42% dla naiwnej unii jako dolną granicę. "
            "Docelowo = 1.0: wszystkie klasy połączone z korzeniem hierarchii."
        ),
    },
    "average_depth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "higher after merge",
        "interpretation": (
            "Średnia głębokość hierarchii klas (śr. liczba krawędzi SubClassOf od "
            "owl:Thing do klasy). Wzrost po merge = klasy jednej ontologii zagnieżdżone "
            "głębiej w hierarchii drugiej przez nowe cross-ontology is-a."
        ),
    },
    "max_depth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "higher after merge",
        "interpretation": (
            "Maksymalna głębokość drzewa klas (najdłuższa ścieżka od korzenia do liścia). "
            "Wzrost = encje jednej ontologii zostały zagnieżdżone głębiej w hierarchii drugiej."
        ),
    },
    "average_breadth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "context-dependent",
        "interpretation": (
            "Średnia liczba bezpośrednich podklas na węzeł posiadający dzieci. "
            "Wzrost = klasy jednej ontologii zyskały podklasy z drugiej; "
            "bardzo wysoka wartość sugeruje brak pośrednich kategorii taksonomicznych."
        ),
    },
    "max_breadth": {
        "source": "self-implemented",
        "categories": ["Hierarchy Integration Quality"],
        "target": "context-dependent",
        "interpretation": (
            "Maksymalna liczba bezpośrednich podklas jednej klasy. "
            "Bardzo wysoka wartość = 'klasa-worek' skupiająca wiele pojęć bez pośrednich "
            "poziomów — sygnał do wprowadzenia dodatkowych kategorii taksonomicznych."
        ),
    },
    # ── Accuracy ──────────────────────────────────────────────────────────────
    "triple_preservation_ratio": {
        "source": "self-implemented",
        "categories": ["Accuracy"],
        "target": "= 1.0",
        "interpretation": (
            "Triple Preservation Ratio = liczba trójek RDF z Onto1 ∪ Onto2 "
            "(porównanie po lokalnych nazwach S/P/O, z normalizacją przez alias LLM) "
            "obecnych w scalonej ontologii / całkowita liczba trójek w Onto1 ∪ Onto2. "
            "Docelowo = 1.0. Niska wartość = duże straty wiedzy źródłowej wymagające uzasadnienia."
        ),
    },
    # ── Understandability ─────────────────────────────────────────────────────
    "annotation_coverage_ratio": {
        "source": "self-implemented",
        "categories": ["Understandability"],
        "target": "= 1.0",
        "interpretation": (
            "Annotation Coverage Ratio = liczba encji (klas + właściwości) posiadających "
            "rdfs:label lub rdfs:comment / całkowita liczba encji. Docelowo = 1.0. "
            "Opatrzone etykietami encje umożliwiają ekspertom domenowym weryfikację "
            "semantycznej poprawności i spójności ontologii po scaleniu."
        ),
    },
}


# ── rdflib helpers ─────────────────────────────────────────────────────────────


def _load_graph(path: str) -> Graph:
    g = Graph()
    g.parse(path)
    for t in list(g.triples((None, _OWL_DISJOINT_WITH, None))):
        g.remove(t)
    return g


def _local(uri: URIRef) -> str:
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


def _classes(g: Graph) -> set[URIRef]:
    result: set[URIRef] = set()
    for s in g.subjects(RDF.type, _OWL_CLASS):
        if isinstance(s, URIRef) and s != _OWL_THING:
            result.add(s)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and s != _OWL_THING:
            result.add(s)
        if isinstance(o, URIRef) and o != _OWL_THING:
            result.add(o)
    return result


def _properties(g: Graph) -> set[URIRef]:
    result: set[URIRef] = set()
    for ptype in _PROP_TYPES:
        for s in g.subjects(RDF.type, ptype):
            if isinstance(s, URIRef):
                result.add(s)
    return result


# ── Self-implemented metric computation ────────────────────────────────────────


def _count_cycles(g: Graph) -> int:
    """Count back-edges in the subClassOf directed graph (each = one cycle)."""
    adj: dict[URIRef, list[URIRef]] = defaultdict(list)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and o != _OWL_THING:
            adj[s].append(o)

    all_nodes: set[URIRef] = set(adj.keys())
    for vs in adj.values():
        all_nodes.update(vs)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[URIRef, int] = {n: WHITE for n in all_nodes}
    cycles = 0

    for start in all_nodes:
        if color[start] != WHITE:
            continue
        stack: list[tuple[URIRef, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node, ci = stack[-1]
            neighbors = adj[node]
            if ci < len(neighbors):
                stack[-1] = (node, ci + 1)
                child = neighbors[ci]
                c = color[child]
                if c == GRAY:
                    cycles += 1
                elif c == WHITE:
                    color[child] = GRAY
                    stack.append((child, 0))
            else:
                color[node] = BLACK
                stack.pop()

    return cycles


def _connectivity_ratio(g: Graph) -> float:
    """Fraction of named classes reachable from owl:Thing via subClassOf."""
    cls = _classes(g)
    if not cls:
        return 1.0
    children: dict[URIRef, set[URIRef]] = defaultdict(set)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            children[o].add(s)
    reachable: set[URIRef] = set()
    queue: deque[URIRef] = deque([_OWL_THING])
    visited: set[URIRef] = {_OWL_THING}
    while queue:
        node = queue.popleft()
        for child in children.get(node, set()):
            if child not in visited:
                visited.add(child)
                if child in cls:
                    reachable.add(child)
                queue.append(child)
    return len(reachable) / len(cls)


def _hierarchy_stats(g: Graph, cls: set[URIRef]) -> dict[str, float]:
    """Compute ALC, depth and breadth metrics from the subClassOf hierarchy."""
    if not cls:
        return {
            "ALC": 0.0,
            "average_depth": 0.0,
            "max_depth": 0.0,
            "average_breadth": 0.0,
            "max_breadth": 0.0,
        }

    children: dict[URIRef, list[URIRef]] = defaultdict(list)
    for s, _, o in g.triples((None, _SUB, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and s in cls:
            children[o].append(s)

    alc = float(sum(1 for c in cls if not children.get(c)))

    depths: dict[URIRef, int] = {}
    queue: deque[tuple[URIRef, int]] = deque([(_OWL_THING, 0)])
    visited: set[URIRef] = {_OWL_THING}
    while queue:
        node, d = queue.popleft()
        for child in children.get(node, []):
            if child not in visited:
                visited.add(child)
                depths[child] = d + 1
                queue.append((child, d + 1))

    depth_vals = list(depths.values())
    avg_depth = sum(depth_vals) / len(depth_vals) if depth_vals else 0.0
    max_depth = float(max(depth_vals)) if depth_vals else 0.0

    breadths = [len(ch) for node, ch in children.items() if node in cls and ch]
    avg_breadth = sum(breadths) / len(breadths) if breadths else 0.0
    max_breadth = float(max(breadths)) if breadths else 0.0

    return {
        "ALC": alc,
        "average_depth": round(avg_depth, 4),
        "max_depth": max_depth,
        "average_breadth": round(avg_breadth, 4),
        "max_breadth": max_breadth,
    }


_ALIAS_PRED = "http://merged#alias"


def _build_alias_maps(
    g: Graph,
    onto1_locals: set[str],
    onto2_locals: set[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build local-name alias maps from merged graph's `merged#alias` triples.

    Returns (old_to_new, new_to_source) where:
      old_to_new: OldLocalName → NewLocalName  (for renaming normalisation)
      new_to_source: NewLocalName → 'onto1' | 'onto2' | 'both'  (attribution)
    """
    old_to_new: dict[str, str] = {}
    new_to_source: dict[str, str] = {}
    for s, p, o in g:
        if str(p) != _ALIAS_PRED or not isinstance(s, URIRef) or not isinstance(o, Literal):
            continue
        parts = str(o).split(";;", 1)
        if len(parts) != 2 or not parts[1]:
            continue
        old_local = parts[1]
        new_local = _local(s)
        old_to_new[old_local] = new_local
        in1 = old_local in onto1_locals
        in2 = old_local in onto2_locals
        src = "both" if in1 and in2 else ("onto1" if in1 else ("onto2" if in2 else ""))
        if src:
            existing = new_to_source.get(new_local)
            new_to_source[new_local] = (
                "both" if existing and existing != src else src
            )
    return old_to_new, new_to_source


def _compute_self_metrics(
    g: Graph,
    onto1_entities: set[URIRef],
    onto2_entities: set[URIRef],
    union: Graph | None = None,
) -> dict[str, float]:
    cls = _classes(g)
    prop = _properties(g)
    n_c = len(cls)

    onto1_locals = {_local(e) for e in onto1_entities}
    onto2_locals = {_local(e) for e in onto2_entities}

    # Alias-aware source attribution.
    #   - Original URI from onto1/onto2 → precise attribution by URI membership.
    #   - New URI (introduced by the LLM, e.g. zz::MedicalSurgery): attribute by alias
    #     triple, mapping back to the source ontology of the original local name.
    # Without this, every LLM rename zeroes the cross-onto and intra-onto counters.
    _, new_to_source = _build_alias_maps(g, onto1_locals, onto2_locals)

    def _from_onto1(u) -> bool:
        if not isinstance(u, URIRef):
            return False
        if u in onto1_entities:
            return True
        if u in onto2_entities:
            return False
        return new_to_source.get(_local(u)) in ("onto1", "both")

    def _from_onto2(u) -> bool:
        if not isinstance(u, URIRef):
            return False
        if u in onto2_entities:
            return True
        if u in onto1_entities:
            return False
        return new_to_source.get(_local(u)) in ("onto2", "both")

    # ARC — classes without a named parent
    has_named_parent = {
        s
        for s, _, o in g.triples((None, _SUB, None))
        if isinstance(s, URIRef)
        and isinstance(o, URIRef)
        and o != _OWL_THING
        and s in cls
    }
    arc = float(len(cls - has_named_parent))

    cycle_count = float(_count_cycles(g))

    unique_local = len({_local(c) for c in cls})
    syntactic_uniqueness_ratio = unique_local / n_c if n_c else 1.0

    # Cross-ontology metrics (alias-aware)
    cross_sub = sum(
        1
        for s, _, o in g.triples((None, _SUB, None))
        if (_from_onto1(s) and _from_onto2(o)) or (_from_onto2(s) and _from_onto1(o))
    )
    cross_rel = sum(
        1
        for s, _, o in g
        if (_from_onto1(s) and _from_onto2(o)) or (_from_onto2(s) and _from_onto1(o))
    )

    connectivity = _connectivity_ratio(g)

    # Triple preservation ratio vs union
    # BNode objects are excluded: their internal IDs differ across parse sessions,
    # so str(bnode) comparisons produce false negatives for restrictions/unions.
    if union is not None:
        old_to_new, _ = _build_alias_maps(g, onto1_locals, onto2_locals)

        def _norm(local: str) -> str:
            return old_to_new.get(local, local)

        def _key(s, p, o) -> tuple[str, str, str]:
            return (
                _local(s),
                _local(p),
                _local(o) if isinstance(o, URIRef) else str(o),
            )

        def _key_norm(s, p, o) -> tuple[str, str, str]:
            return (
                _norm(_local(s)),
                _norm(_local(p)),
                _norm(_local(o)) if isinstance(o, URIRef) else str(o),
            )

        union_triples = {
            _key_norm(s, p, o)
            for s, p, o in union
            if isinstance(s, URIRef) and not isinstance(o, BNode)
        }
        g_triples = {
            _key(s, p, o)
            for s, p, o in g
            if isinstance(s, URIRef) and not isinstance(o, BNode)
        }
        tpr = (
            len(g_triples & union_triples) / len(union_triples)
            if union_triples
            else 1.0
        )

        # New intra-ontology relations (alias-aware): triples in g where both S and O
        # belong to the SAME source (including renamed entities), but the triple
        # (by local-name key) is absent from union.
        union_keys = {
            (_local(s), _local(p), _local(o))
            for s, p, o in union
            if isinstance(s, URIRef) and isinstance(o, URIRef)
        }
        new_intra_rel = float(
            sum(
                1
                for s, p, o in g
                if isinstance(s, URIRef)
                and isinstance(o, URIRef)
                and (
                    (_from_onto1(s) and _from_onto1(o))
                    or (_from_onto2(s) and _from_onto2(o))
                )
                and (_local(s), _local(p), _local(o)) not in union_keys
            )
        )

    else:
        tpr = 1.0
        new_intra_rel = 0.0

    entities = cls | prop
    n_e = len(entities)
    annotated = sum(
        1
        for e in entities
        if any(True for _ in g.objects(e, _LABEL))
        or any(True for _ in g.objects(e, _COMMENT))
    )
    annotation_coverage = annotated / n_e if n_e else 0.0

    hierarchy = _hierarchy_stats(g, cls)

    return {
        "ARC": arc,
        "cycle_count": cycle_count,
        "syntactic_uniqueness_ratio": round(syntactic_uniqueness_ratio, 4),
        "cross_onto_subclassof_count": float(cross_sub),
        "cross_onto_relations_count": float(cross_rel),
        "new_intra_onto_relations_count": new_intra_rel,
        "connectivity_ratio": round(connectivity, 4),
        "triple_preservation_ratio": round(tpr, 4),
        "annotation_coverage_ratio": round(annotation_coverage, 4),
        **hierarchy,
    }


# ── HermiT reasoner check ─────────────────────────────────────────────────────

# XSD datatypes absent from the OWL 2 datatype map — HermiT rejects them.
# See: https://www.w3.org/TR/owl2-syntax/#Datatype_Maps
_XSD_UNSUPPORTED = frozenset(
    [
        XSD.date,
        XSD.time,
        XSD.duration,
        XSD.gYear,
        XSD.gYearMonth,
        XSD.gMonth,
        XSD.gMonthDay,
        XSD.gDay,
    ]
)


def _strip_hermit_unsupported(g: Graph) -> Graph:
    """Return a copy of g safe for HermiT.

    Removes all blank-node restrictions (owl:allValuesFrom / owl:someValuesFrom /
    rdfs:range) that reference XSD datatypes not in the OWL 2 datatype map,
    plus any remaining references to those blank nodes.
    """
    bad_bnodes: set[BNode] = set()
    for s, _, o in g:
        if (isinstance(o, URIRef) and o in _XSD_UNSUPPORTED) or (
            isinstance(o, Literal) and o.datatype in _XSD_UNSUPPORTED
        ):
            if isinstance(s, BNode):
                bad_bnodes.add(s)

    result = Graph()
    for s, p, o in g:
        if isinstance(o, URIRef) and o in _XSD_UNSUPPORTED:
            continue
        if isinstance(o, Literal) and o.datatype in _XSD_UNSUPPORTED:
            continue
        if isinstance(s, BNode) and s in bad_bnodes:
            continue
        if isinstance(o, BNode) and o in bad_bnodes:
            continue
        result.add((s, p, o))
    return result


def _reasoner_check(g: Graph, label: str) -> dict[str, float | None]:
    """Run HermiT via owlready2 and return number of unsatisfiable classes."""
    try:
        import owlready2
    except ImportError:
        print(
            f"  [HermiT/{label}] owlready2 not installed — skipping (pip install owlready2)"
        )
        return {"unsatisfiable_classes": None}

    import os
    import tempfile

    g_safe = _strip_hermit_unsupported(g)
    stripped = len(g) - len(g_safe)
    if stripped:
        print(
            f"  [HermiT/{label}] stripped {stripped} triples with unsupported XSD datatypes"
        )

    with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as f:
        g_safe.serialize(destination=f.name, format="xml")
        tmp_path = f.name

    try:
        print(f"  → HermiT [{label}] …", end=" ", flush=True)
        world = owlready2.World()
        onto = world.get_ontology(f"file://{tmp_path}").load()
        with onto:
            owlready2.sync_reasoner_hermit(world, infer_property_values=False)
        unsat = list(world.inconsistent_classes())
        print(f"{len(unsat)} unsatisfiable classes")
        return {"unsatisfiable_classes": float(len(unsat))}
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return {"unsatisfiable_classes": None}
    finally:
        os.unlink(tmp_path)


# ── HTML report ───────────────────────────────────────────────────────────────

_CAT_ABBR: dict[str, str] = {cat: abbr for cat, (abbr, _) in _CATEGORIES.items()}
_CAT_COLOR: dict[str, str] = {cat: color for cat, (_, color) in _CATEGORIES.items()}

_SOURCE_BORDER: dict[str, str] = {
    "self-implemented": "#27ae60",
    "hermit_reasoner": "#8e44ad",
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ontology quality metrics — {folder}</title>
<style>
  body  {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1   {{ font-size: 1.4rem; margin-bottom: 0.3rem; }}
  p.sub {{ color: #666; font-size: 0.9rem; margin: 0 0 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.87rem; }}
  th, td {{ padding: 0.5rem 0.7rem; text-align: left; vertical-align: top;
            border: 1px solid #d0d0d0; }}
  th {{ background: #2c3e50; color: #fff; white-space: nowrap; }}
  tr:nth-child(even) {{ background: #f7f7f7; }}
  tr:hover {{ background: #eaf3fb; }}
  td.num   {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.na    {{ text-align: center; color: #aaa; }}
  td.src   {{ font-size: 0.78rem; white-space: nowrap; }}
  td.tgt   {{ font-size: 0.78rem; color: #666; white-space: nowrap; }}
  td.cats  {{ max-width: 230px; }}
  td.interp {{ font-size: 0.82rem; color: #444; max-width: 320px; }}
  .badge  {{ display: inline-block; padding: 2px 7px; border-radius: 3px;
             font-size: 0.72rem; margin: 1px; color: #fff; white-space: nowrap; }}
  .legend {{ margin-top: 1.5rem; font-size: 0.8rem; }}
  .legend h3 {{ font-size: 0.85rem; margin: 0.6rem 0 0.3rem; color: #555; }}
  .legend-row {{ display: flex; flex-wrap: wrap; gap: 0.8rem; }}
  .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .dot  {{ width: 13px; height: 13px; border-radius: 2px; display: inline-block; flex-shrink: 0; }}
  .src-dot {{ width: 4px; height: 18px; border-radius: 2px; display: inline-block; flex-shrink: 0; }}
  .note {{ margin-top: 1rem; font-size: 0.8rem; color: #888; font-style: italic; }}
</style>
</head>
<body>
<h1>Ontology quality metrics &mdash; <code>{folder}</code></h1>
<p class="sub">7-dimensional evaluation framework</p>
<table>
  <thead>
    <tr>
      <th>Metric</th>
      <th>union_input</th>
      {applied_col_header}
      <th>merged_ontology</th>
      <th>Target</th>
      <th>Source</th>
      <th>Categories</th>
      <th>Interpretation</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
{legend}
<p class="note">
  Note: Domain Coherence and Conciseness (semantic) require manual case-study evaluation —
  no fully automated proxy exists for detecting semantically equivalent but differently-named concepts.
</p>
</body>
</html>
"""

_LEGEND_TEMPLATE = """\
<div class="legend">
  <h3>Source</h3>
  <div class="legend-row">
    <span class="legend-item"><span class="src-dot" style="background:#27ae60"></span> self-implemented</span>
    <span class="legend-item"><span class="src-dot" style="background:#8e44ad"></span> hermit_reasoner</span>
  </div>
  <h3>Quality dimension</h3>
  <div class="legend-row">
{cat_legend}
  </div>
</div>"""


def _fmt(v: float | None) -> str:
    if v is None:
        return '<td class="na">N/A</td>'
    if v == int(v) and abs(v) < 1e9:
        return f'<td class="num">{int(v)}</td>'
    return f'<td class="num">{v:.4f}</td>'


def _cat_badges(categories: list[str]) -> str:
    parts = []
    for cat in categories:
        color = _CAT_COLOR.get(cat, "#999")
        parts.append(f'<span class="badge" style="background:{color}">{cat}</span>')
    return "".join(parts)


def _write_html(
    rows: list[dict],
    out_path: Path,
    folder: str,
    has_applied: bool,
) -> None:
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_metric[r["metric"]][r["graph"]] = r["value"]

    html_rows: list[str] = []
    for metric_name, meta in _REGISTRY.items():
        vals = by_metric.get(metric_name, {})
        u_val = vals.get("union_input")
        m_val = vals.get("merged_ontology")
        a_val = vals.get("applied_alignments") if has_applied else None
        if u_val is None and m_val is None and a_val is None:
            continue
        border = _SOURCE_BORDER.get(meta["source"], "#ccc")
        badges = _cat_badges(meta["categories"])
        applied_cell = _fmt(a_val) if has_applied else ""

        html_rows.append(
            f'    <tr style="border-left: 3px solid {border}">\n'
            f"      <td><strong>{metric_name}</strong></td>\n"
            f"      {_fmt(u_val)}\n"
            f"      {applied_cell}\n"
            f"      {_fmt(m_val)}\n"
            f'      <td class="tgt">{meta["target"]}</td>\n'
            f'      <td class="src">{meta["source"]}</td>\n'
            f'      <td class="cats">{badges}</td>\n'
            f'      <td class="interp">{meta["interpretation"]}</td>\n'
            f"    </tr>"
        )

    applied_col_header = "<th>applied_alignments</th>" if has_applied else ""

    cat_legend_lines = []
    for cat, (_, color) in _CATEGORIES.items():
        cat_legend_lines.append(
            f'    <span class="legend-item">'
            f'<span class="dot" style="background:{color}"></span> {cat}</span>'
        )
    legend = _LEGEND_TEMPLATE.format(cat_legend="\n".join(cat_legend_lines))

    html = _HTML_TEMPLATE.format(
        folder=folder,
        applied_col_header=applied_col_header,
        rows="\n".join(html_rows),
        legend=legend,
    )
    out_path.write_text(html, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute ontology quality metrics based on 7 academic quality dimensions."
    )
    parser.add_argument("folder_name", help="Subfolder under tests/inputs/ and tests/outputs/")
    args = parser.parse_args()

    folder = args.folder_name
    repo_root = Path(__file__).parent.parent
    input_dir = repo_root / "tests" / "inputs" / folder
    output_dir = repo_root / "tests" / "outputs" / folder
    out_csv = output_dir / "metrics_def.csv"

    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    input_files = sorted(input_dir.glob("*.owl"))
    if len(input_files) != 2:
        print(
            f"Expected exactly 2 .owl files in {input_dir}, found {len(input_files)}",
            file=sys.stderr,
        )
        sys.exit(1)

    merged_path = output_dir / "merged_ontology.owl"
    applied_path = output_dir / "applied_alignments.owl"

    if not merged_path.exists():
        print(f"merged_ontology.owl not found in {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading ontologies for: {folder}")
    onto1 = _load_graph(str(input_files[0]))
    onto2 = _load_graph(str(input_files[1]))
    union = Graph()
    for t in onto1:
        union.add(t)
    for t in onto2:
        union.add(t)
    merged = _load_graph(str(merged_path))
    applied = _load_graph(str(applied_path)) if applied_path.exists() else None

    print(f"  onto1:              {len(onto1)} triples")
    print(f"  onto2:              {len(onto2)} triples")
    print(f"  union_input:        {len(union)} triples")
    print(f"  merged_ontology:    {len(merged)} triples")
    if applied is not None:
        print(f"  applied_alignments: {len(applied)} triples")
    else:
        print("  applied_alignments: not found — skipped")

    # Entity sets for cross-ontology metrics (URI-based source attribution)
    onto1_entities: set[URIRef] = {s for s, _, _ in onto1 if isinstance(s, URIRef)}
    onto2_entities: set[URIRef] = {s for s, _, _ in onto2 if isinstance(s, URIRef)}

    # ── Self-implemented metrics ───────────────────────────────────────────────
    print("\nComputing self-implemented metrics …")
    graph_objects: dict[str, Graph] = {
        "union_input": union,
        "merged_ontology": merged,
    }
    if applied is not None:
        graph_objects["applied_alignments"] = applied

    self_metrics: dict[str, dict[str, float | None]] = {}
    for name, g in graph_objects.items():
        union_arg = None if name == "union_input" else union
        self_metrics[name] = _compute_self_metrics(
            g, onto1_entities, onto2_entities, union_arg
        )
        print(f"  {name}: done")

    # ── HermiT reasoner ───────────────────────────────────────────────────────
    print("\nRunning HermiT reasoner …")
    for name, g in graph_objects.items():
        self_metrics[name].update(_reasoner_check(g, name))

    # ── Assemble rows ──────────────────────────────────────────────────────────
    graph_names = ["union_input", "merged_ontology"] + (
        ["applied_alignments"] if applied is not None else []
    )

    rows: list[dict] = []
    for graph_name in graph_names:
        for metric_name, meta in _REGISTRY.items():
            value = self_metrics[graph_name].get(metric_name)
            if value is None:
                continue
            rows.append(
                {
                    "graph": graph_name,
                    "metric": metric_name,
                    "value": value,
                    "source": meta["source"],
                    "categories": ", ".join(meta["categories"]),
                    "target": meta["target"],
                    "interpretation": meta["interpretation"],
                }
            )

    if not rows:
        print("No metrics collected.", file=sys.stderr)
        sys.exit(1)

    # ── Write CSV ──────────────────────────────────────────────────────────────
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "graph",
                "metric",
                "value",
                "target",
                "source",
                "categories",
                "interpretation",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nMetrics written to {out_csv}")

    # ── Write HTML ─────────────────────────────────────────────────────────────
    out_html = out_csv.with_suffix(".html")
    _write_html(rows, out_html, folder, applied is not None)
    print(f"Report  written to {out_html}\n")

    # ── Console summary ────────────────────────────────────────────────────────
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_metric[r["metric"]][r["graph"]] = r["value"]

    has_app = applied is not None
    col = max(len(m) for m in _REGISTRY)
    hdr = (
        f"{'metric':<{col}}  {'union_input':>15}  {'applied_alignments':>20}"
        f"  {'merged_ontology':>16}  target"
        if has_app
        else f"{'metric':<{col}}  {'union_input':>15}  {'merged_ontology':>16}  target"
    )
    print(hdr)
    print("─" * len(hdr))
    for metric_name, meta in _REGISTRY.items():
        vals = by_metric.get(metric_name, {})
        u = vals.get("union_input")
        m = vals.get("merged_ontology")
        if not vals:
            continue

        def _fs(v: float | None, w: int) -> str:
            if v is None:
                return f"{'—':>{w}}"
            if v == int(v) and abs(v) < 1e9:
                return f"{int(v):>{w}}"
            return f"{v:>{w}.4f}"

        u_s = _fs(u, 15)
        m_s = _fs(m, 16)
        tgt = meta["target"]
        if has_app:
            a = vals.get("applied_alignments")
            a_s = _fs(a, 20)
            print(f"{metric_name:<{col}}{u_s}{a_s}{m_s}  {tgt}")
        else:
            print(f"{metric_name:<{col}}{u_s}{m_s}  {tgt}")


if __name__ == "__main__":
    main()
