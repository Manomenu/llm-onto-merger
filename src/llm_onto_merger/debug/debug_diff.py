from pathlib import Path

from rdflib import Graph, URIRef

from ..extract_environments.merge_environment import MergeEnvironment
from ..logger import get_logger
from ..ontology import local_name

log = get_logger(__name__)


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

    Triples are compared by local name (URI-agnostic) so that a different
    namespace prefix for the same concept still matches correctly.
    Blank nodes and non-URIRef triples are excluded.
    """
    for i, (env, merged) in enumerate(zip(merge_environments, merged_graphs)):
        def _names(graph: Graph) -> set[tuple[str, str, str]]:
            return {
                (local_name(str(s)), local_name(str(p)), local_name(str(o)))
                for s, p, o in graph
                if isinstance(s, URIRef) and isinstance(o, URIRef)
            }

        # env.onto_2 already has entity2 → entity1 renaming from pre-extraction step.
        pre = _names(env.onto_1) | _names(env.onto_2)
        post = _names(merged)

        deleted = sorted(pre - post)
        added = sorted(post - pre)

        path = out_dir / f"env_diff_{i}.txt"
        with path.open("w") as f:
            f.write("[Deleted]\n")
            for s, p, o in deleted:
                f.write(f"  ({s}, {p}, {o})\n")
            f.write("[Added]\n")
            for s, p, o in added:
                f.write(f"  ({s}, {p}, {o})\n")

        log.info(
            "[debug] %s  deleted: %d  added: %d", path.name, len(deleted), len(added)
        )
