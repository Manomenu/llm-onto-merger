import itertools
import string
from collections import deque

from rdflib import Graph, URIRef

from ..alignment.alignment import Alignment
from ..ontology import KG2CODE_PREAMBLE, graph_to_string, local_name

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


def _namespace_of(uri: str) -> str:
    """Return the namespace prefix of a URI (everything up to and including # or last /)."""
    return (uri.rsplit("#", 1)[0] + "#") if "#" in uri else (uri.rsplit("/", 1)[0] + "/")


def _build_namespace_codec(
    onto_1: Graph,
    onto_2: Graph,
) -> tuple[dict[str, str], dict[str, str]]:
    """Assign a short alphabetic code (aa, ab, …) to each unique namespace prefix
    found among subject URIs in onto_1 and onto_2.

    Typically 2-3 namespaces total — far fewer codes than one-per-URI.

    Returns:
        uri_to_code  — full URI → namespace code  (for use in graph_to_string)
        code_to_ns   — namespace code → namespace prefix  (for URI reconstruction)

    Reconstruction: full_uri = code_to_ns[code] + entity.name
    """
    namespaces = sorted({
        _namespace_of(str(s))
        for g in (onto_1, onto_2)
        for s, _, _ in g
        if isinstance(s, URIRef)
    })
    codes = (
        "".join(combo)
        for length in itertools.count(2)
        for combo in itertools.product(_CODEC_CHARS, repeat=length)
    )
    ns_to_code: dict[str, str] = {}
    code_to_ns: dict[str, str] = {}
    for ns, code in zip(namespaces, codes):
        ns_to_code[ns] = code
        code_to_ns[code] = ns

    uri_to_code: dict[str, str] = {
        str(s): ns_to_code[_namespace_of(str(s))]
        for g in (onto_1, onto_2)
        for s, _, _ in g
        if isinstance(s, URIRef) and _namespace_of(str(s)) in ns_to_code
    }
    return uri_to_code, code_to_ns


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
    ) -> None:
        self.onto_1 = onto_1
        self.onto_2 = onto_2
        self.alignments = alignments
        self.border1: deque[URIRef] = border1 if border1 is not None else deque()
        self.border2: deque[URIRef] = border2 if border2 is not None else deque()

    @property
    def chars_count(self) -> int:
        onto_chars = (len(self.onto_1) + len(self.onto_2)) * 3 * _CHARS_PER_TRIPLE_TERM
        border_chars = (len(self.border1) + len(self.border2)) * _CHARS_PER_BORDER_NODE
        alignment_chars = len(self.alignments) * 2 * _CHARS_PER_TRIPLE_TERM
        return onto_chars + border_chars + alignment_chars

    def to_string(self) -> tuple[str, dict[str, str]]:
        """Serialise the environment as a KG2Code prompt string.

        Entity URIs are replaced with short alphabetic codes to reduce prompt
        size.  Returns (prompt_string, code_to_uri) so the caller can restore
        full URIs from the LLM response.
        """
        uri_to_code, code_to_uri = _build_namespace_codec(self.onto_1, self.onto_2)
        border1_str = ", ".join(local_name(u) for u in self.border1)
        border2_str = ", ".join(local_name(u) for u in self.border2)
        alignments_str = "\n".join(al.to_string() for al in self.alignments)
        text = f"""
            {KG2CODE_PREAMBLE}


            [Ontology_1]:
            {graph_to_string(self.onto_1, uri_to_code)}
            [Border_1]:
            {border1_str}

            [Ontology_2]:
            {graph_to_string(self.onto_2, uri_to_code)}
            [Border_2]:
            {border2_str}

            [Alignments]:
            {alignments_str}
        """
        return text, code_to_uri
