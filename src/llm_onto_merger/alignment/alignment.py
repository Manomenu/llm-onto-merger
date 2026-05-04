from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class Alignment(BaseModel):
    entity1: str
    entity2: str
    measure: float
    relation: str


class AlignmentModule(ABC):
    @abstractmethod
    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> list[Alignment]:
        """Compute alignment between base and candidate ontologies."""


alignment_modules_dict = {
    "aml": AlignmentModule,
}
