from pathlib import Path

from rdflib import Graph, URIRef

from ..extract_environments.merge_environment import MergeEnvironment
from ..logger import get_logger
from ..ontology import local_name

log = get_logger(__name__)


def _normalize_onto2(env: MergeEnvironment) -> Graph:
    """Substitute entity2 → entity1 in onto2 for '=' alignments before diffing.

    This makes the pre-merge triples comparable to post-merge output, where the
    LLM was instructed to use entity1 as the canonical URI.
    """
    uri_map = {
        al.entity2: al.entity1
        for al in env.alignments
        if al.relation == "=" and al.entity2 != al.entity1
    }
    if not uri_map:
        return env.onto_2

    normalized = Graph()
    for s, p, o in env.onto_2:
        new_s = URIRef(uri_map[str(s)]) if isinstance(s, URIRef) and str(s) in uri_map else s
        new_o = URIRef(uri_map[str(o)]) if isinstance(o, URIRef) and str(o) in uri_map else o
        normalized.add((new_s, p, new_o))
    return normalized


def save_diff_debug(
    merge_environments: list[MergeEnvironment],
    merged_graphs: list[Graph],
    out_dir: Path,
) -> None:
    """Write env_diff_0/1/…txt for each environment.

    Format:
        [Deleted]
          (SubjectLocalName, PredicateLocalName, ObjectLocalName)
          ...
        [Added]
          (SubjectLocalName, PredicateLocalName, ObjectLocalName)
          ...

    Pre-merge onto2 triples are normalized (entity2 → entity1 for '=' alignments)
    before comparison so the diff reflects semantic changes, not just URI renaming.
    """
    for i, (env, merged) in enumerate(zip(merge_environments, merged_graphs)):
        # Build pre-merge triple set: onto1 + normalized onto2
        normalized_onto2 = _normalize_onto2(env)
        pre: set[tuple[str, str, str]] = set()
        for s, p, o in env.onto_1:
            pre.add((str(s), str(p), str(o)))
        for s, p, o in normalized_onto2:
            pre.add((str(s), str(p), str(o)))

        # Build post-merge triple set
        post: set[tuple[str, str, str]] = {
            (str(s), str(p), str(o)) for s, p, o in merged
        }

        deleted = sorted(pre - post)
        added = sorted(post - pre)

        path = out_dir / f"env_diff_{i}.txt"
        with path.open("w") as f:
            f.write("[Deleted]\n")
            for s, p, o in deleted:
                f.write(f"  ({local_name(s)}, {local_name(p)}, {local_name(o)})\n")
            f.write("[Added]\n")
            for s, p, o in added:
                f.write(f"  ({local_name(s)}, {local_name(p)}, {local_name(o)})\n")

        log.info(
            "[debug] %s  deleted: %d  added: %d", path.name, len(deleted), len(added)
        )
