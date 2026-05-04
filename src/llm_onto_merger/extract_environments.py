import owlready2

from .alignment.alignment import Alignment


class MergeEnvironmentConfig:
    def __init__(self, max_chars: int = 10_000) -> None:
        self.max_chars = max_chars


class MergeEnvironment:
    def __init__(
        self,
        onto_1: owlready2.Ontology,
        onto_2: owlready2.Ontology,
        alignments: list[Alignment],
    ) -> None:
        self.onto_1 = onto_1
        self.onto_2 = onto_2
        self.alignments = alignments

    def to_string(self) -> str:
        pass


def extract_environments(
    onto_1: owlready2.Ontology,
    onto_2: owlready2.Ontology,
    alignments: list[Alignment],
    config: MergeEnvironmentConfig,
) -> list[MergeEnvironment]:
    pass
