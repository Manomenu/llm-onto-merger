from pydantic import BaseModel
from rdflib import Graph, Literal, URIRef

from ..logger import get_logger
from .uri import namespace_of

log = get_logger(__name__)

ALIAS_PREDICATE_CODED = "zz::alias"
ALIAS_PREDICATE = "http://merged#alias"

KG2CODE_PREAMBLE = """
Each ontology entity is represented as:
  Entity(uri, tuples)
where:
  uri    — 'code::LocalName'  uniquely identifies the entity, e.g. 'aa::Person'
  tuples — outgoing triples: list of (subject_uri, predicate_uri, object_uri_or_literal)
           every URI element uses the same 'code::LocalName' encoding
           literal values (strings, numbers) are written as-is without a code prefix

Example:
  Entity('aa::Person', tuples=[
      ('aa::Person', 'af::subClassOf', 'ab::Animal'),
      ('aa::Person', 'ae::type', 'ah::Class'),
  ])

When generating a Merged_Ontology you MUST use the same code prefixes for existing entities.
For entirely new concepts you may use 'zz::NewName'.
"""


class Entity(BaseModel):
    uri: str
    tuples: list[tuple[str, str, str]]


def _encode(uri: str, ns_to_code: dict[str, str]) -> str:
    """Encode a full URI as 'code::LocalName'. Falls back to the bare URI on miss."""
    ns = namespace_of(uri)
    code = ns_to_code.get(ns)
    local = uri[len(ns):]
    return f"{code}::{local}" if code and local else uri


def _decode(coded: str, code_to_ns: dict[str, str]) -> URIRef | Literal:
    """Decode 'code::LocalName' → URIRef. Falls back to Literal for unknowns.

    Emits a warning when the value looks URI-shaped (contains '::') but the
    namespace code is unknown or the local name is empty.  No warning is
    emitted for values without '::' that fall back to Literal — those are
    legitimately literal object values (e.g. rdfs:comment text).
    """
    idx = coded.find("::")
    if idx > 0:
        code, local = coded[:idx], coded[idx + 2:]
        ns = code_to_ns.get(code)
        if ns and local:
            return URIRef(ns + local)
        if not ns:
            log.warning(
                "Decoder: unknown namespace code '%s' in '%s' — falling back to Literal",
                code, coded,
            )
        elif not local:
            log.warning(
                "Decoder: empty local name after '::' in '%s' — falling back to Literal",
                coded,
            )
    if coded.startswith("http"):
        return URIRef(coded)
    return Literal(coded)


def graph_to_string(graph: Graph, ns_to_code: dict[str, str]) -> str:
    """Render all entities in *graph* as KG2Code Entity(...) declarations.

    Every URI — subject, predicate, object — is encoded as 'code:LocalName'
    using ns_to_code so the full URI can be reconstructed from the response.
    Does NOT include KG2CODE_PREAMBLE.
    """
    subjects = sorted({s for s, _, _ in graph if isinstance(s, URIRef)}, key=str)
    lines = []
    for subj in subjects:
        subj_enc = _encode(str(subj), ns_to_code)
        tuple_strs = [
            f"('{subj_enc}', '{_encode(str(p), ns_to_code)}', "
            f"'{str(o) if isinstance(o, Literal) else _encode(str(o), ns_to_code)}')"
            for _, p, o in graph.triples((subj, None, None))
        ]
        lines.append(f"Entity('{subj_enc}', tuples=[{', '.join(tuple_strs)}])")
    return "\n".join(lines)


def _is_valid_entity(e: Entity, code_to_ns: dict[str, str]) -> bool:
    uri = e.uri.strip()
    if not uri:
        return False
    idx = uri.find("::")
    if idx > 0:
        return uri[:idx] in code_to_ns and bool(uri[idx + 2:])
    return uri.startswith("http")


def _decode_alias_literal(s: str, code_to_ns: dict[str, str]) -> URIRef | None:
    """Decode an alias literal encoded as 'code;;LocalName' → URIRef.

    Emits a warning on every failure path because an alias-predicate object is
    always meant to encode an old URI — anything else is a malformed LLM
    response (missing ';;' separator, unknown code, or empty local name).
    """
    idx = s.find(";;")
    if idx < 0:
        log.warning(
            "Alias decoder: missing ';;' separator in alias literal '%s' — discarded",
            s,
        )
        return None
    code, local = s[:idx], s[idx + 2:]
    ns = code_to_ns.get(code)
    if ns and local:
        return URIRef(ns + local)
    if not ns:
        log.warning(
            "Alias decoder: unknown namespace code '%s' in alias literal '%s' — discarded",
            code, s,
        )
    elif not local:
        log.warning(
            "Alias decoder: empty local name in alias literal '%s' — discarded",
            s,
        )
    return None


def build_alias_map(graphs: list[Graph], code_to_ns: dict[str, str]) -> dict[str, str]:
    """Extract alias triples and return {old_uri: new_uri}.

    Scans for (subject, http://merged#alias, literal) triples where the literal
    encodes an old URI in 'code;;LocalName' format.
    """
    alias_pred = URIRef(ALIAS_PREDICATE)
    result: dict[str, str] = {}
    for graph in graphs:
        for s, p, o in graph.triples((None, alias_pred, None)):
            if isinstance(s, URIRef) and isinstance(o, Literal):
                old_uri = _decode_alias_literal(str(o), code_to_ns)
                if old_uri:
                    result[str(old_uri)] = str(s)
    return result


def entities_to_graph(entities: list[Entity], code_to_ns: dict[str, str]) -> Graph:
    """Reconstruct an rdflib Graph from LLM-returned Entity list.

    Every URI element is decoded via code_to_ns.  Unknown codes fall back to
    Literal; triples whose subject or predicate does not decode as URIRef are
    dropped with a warning.
    """
    valid = [e for e in entities if _is_valid_entity(e, code_to_ns)]
    if len(valid) < len(entities):
        log.warning(
            "Dropped %d invalid/placeholder entities from LLM response",
            len(entities) - len(valid),
        )
    graph = Graph()
    dropped_subj = 0
    dropped_pred = 0
    for entity in valid:
        subj = _decode(entity.uri, code_to_ns)
        if not isinstance(subj, URIRef):
            log.warning(
                "Triple group dropped: subject '%s' did not decode as URI",
                entity.uri,
            )
            dropped_subj += 1
            continue
        for _, p_coded, o_coded in entity.tuples:
            p = _decode(p_coded, code_to_ns)
            o = _decode(o_coded, code_to_ns)
            if isinstance(p, URIRef):
                graph.add((subj, p, o))
            else:
                log.warning(
                    "Triple dropped: predicate '%s' did not decode as URI (subject was '%s')",
                    p_coded, entity.uri,
                )
                dropped_pred += 1
    if dropped_subj or dropped_pred:
        log.warning(
            "entities_to_graph summary: dropped %d entities (bad subject) and %d triples (bad predicate)",
            dropped_subj, dropped_pred,
        )
    return graph
