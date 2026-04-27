from abc import ABC, abstractmethod
from pathlib import Path


class AlignmentModule(ABC):
    @abstractmethod
    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> None:
        """Compute alignment between base and candidate ontologies."""


alignment_modules_dict = {
    "aml": AlignmentModule,
}
