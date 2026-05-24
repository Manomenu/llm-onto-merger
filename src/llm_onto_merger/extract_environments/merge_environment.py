import itertools
import string
from collections import deque

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..ontology import KG2CODE_PREAMBLE, graph_to_string

# Calibrated against observed KG2Code serialisation sizes with URI compression.
# Each triple serialises as a Python tuple with three quoted local names:
#   ('Subject', 'relation', 'Object')  →  ~44 chars/tuple
# The Entity() header now uses a 2-char code instead of a full URI:
#   Entity('aa', name='Person', tuples=[  →  ~39 chars/entity (was ~72)
# Savings ≈ 33 chars/entity ÷ avg 3 triples/entity ≈ 11 chars/triple
# Net per triple: ~61 chars  →  3 terms × 20 ≈ 60.
# Border nodes appear as comma-separated local names  →  ~12 chars each.
_CHARS_PER_TRIPLE_TERM = 20   # chars per URI/literal position inside a KG2Code tuple
_CHARS_PER_BORDER_NODE = 12   # avg local-name length + separator in the border list

_CODEC_CHARS = string.ascii_lowercase

_WELL_KNOWN_NS: tuple[str, ...] = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2003/11/swrl#",
    "http://www.w3.org/2003/11/swrlb#",
    "http://www.owl-ontologies.com/2005/08/07/xsp.owl#",
    "http://protege.stanford.edu/plugins/owl/protege#",
)

# Reserved code for entities introduced by the LLM (not from either source ontology).
MERGED_NS = "http://merged#"
MERGED_CODE = "zz"


def _namespace_of(uri: str) -> str:
    """Return the namespace prefix of a URI (everything up to and including # or last /)."""
    return (uri.rsplit("#", 1)[0] + "#") if "#" in uri else (uri.rsplit("/", 1)[0] + "/")


def _encode_border(uri: URIRef, ns_to_code: dict[str, str]) -> str:
    """Encode a border URIRef as 'code:LocalName' for the prompt."""
    s = str(uri)
    ns = _namespace_of(s)
    code = ns_to_code.get(ns)
    local = s[len(ns):]
    return f"{code}::{local}" if code and local else s


def build_namespace_codec(
    onto_1: Graph,
    onto_2: Graph,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], frozenset[str]]:
    """Assign short alphabetic codes to each unique namespace prefix.

    Namespaces are collected from every URIRef position in both ontologies
    (subjects, predicates, objects).  Well-known namespaces are added only
    for the ones not already present in the data.  Code zz is permanently
    reserved for MERGED_NS (entities introduced by the LLM).

    Returns:
        uri_to_code    — full subject URI → namespace code  (for graph_to_string)
        code_to_ns     — code → namespace prefix  (for URI reconstruction)
        ns_to_code     — namespace prefix → code  (for is_well_known by code)
        well_known_codes — frozenset of codes assigned to well-known namespaces
    """
    data_namespaces = {
        _namespace_of(str(node))
        for g in (onto_1, onto_2)
        for s, p, o in g
        for node in (s, p, o)
        if isinstance(node, URIRef)
    }
    # Well-known NS added only if absent from data; zz is reserved, skip it.
    all_namespaces = sorted(data_namespaces | set(_WELL_KNOWN_NS))

    codes = (
        c
        for length in itertools.count(2)
        for c in ("".join(combo) for combo in itertools.product(_CODEC_CHARS, repeat=length))
        if c != MERGED_CODE
    )
    ns_to_code: dict[str, str] = {}
    code_to_ns: dict[str, str] = {}
    for ns, code in zip(all_namespaces, codes):
        ns_to_code[ns] = code
        code_to_ns[code] = ns

    # Reserve zz for merged namespace (LLM-created entities).
    ns_to_code[MERGED_NS] = MERGED_CODE
    code_to_ns[MERGED_CODE] = MERGED_NS

    uri_to_code: dict[str, str] = {
        str(s): ns_to_code[_namespace_of(str(s))]
        for g in (onto_1, onto_2)
        for s, _, _ in g
        if isinstance(s, URIRef) and _namespace_of(str(s)) in ns_to_code
    }
    well_known_codes = frozenset(
        ns_to_code[ns] for ns in _WELL_KNOWN_NS if ns in ns_to_code
    )
    return uri_to_code, code_to_ns, ns_to_code, well_known_codes


class MergeEnvironmentConfig:
    def __init__(self, max_chars: int = 10_000) -> None:
        self.max_chars = max_chars


class MergeEnvironment:
    def __init__(
        self,
        onto_1: Graph,
        onto_2: Graph,
        alignments: list[Alignment],
        border1: deque[URIRef] | None = None,
        border2: deque[URIRef] | None = None,
        ns_to_code: dict[str, str] | None = None,
        code_to_ns: dict[str, str] | None = None,
        tracked_size: int = 0,
    ) -> None:
        self.onto_1 = onto_1
        self.onto_2 = onto_2
        self.alignments = alignments
        self.border1: deque[URIRef] = border1 if border1 is not None else deque()
        self.border2: deque[URIRef] = border2 if border2 is not None else deque()
        self._ns_to_code: dict[str, str] = ns_to_code or {}
        self._code_to_ns: dict[str, str] = code_to_ns or {}
        self.tracked_size: int = tracked_size

    def to_string(self) -> tuple[str, dict[str, str]]:
        """Serialise the environment as a KG2Code prompt string.

        Every URI is encoded as 'code:LocalName' so the LLM can reconstruct
        full URIs from the response.  Returns (prompt_string, code_to_ns).
        """
        border1_str = ", ".join(_encode_border(u, self._ns_to_code) for u in self.border1)
        border2_str = ", ".join(_encode_border(u, self._ns_to_code) for u in self.border2)
        alignments_str = "\n".join(al.to_string() for al in self.alignments)
        text = f"""
            {KG2CODE_PREAMBLE}


            [Ontology_1]:
            {graph_to_string(self.onto_1, self._ns_to_code)}
            [Border_1]:
            {border1_str}

            [Ontology_2]:
            {graph_to_string(self.onto_2, self._ns_to_code)}
            [Border_2]:
            {border2_str}

            [Alignments]:
            {alignments_str}
        """
        return text, self._code_to_ns
