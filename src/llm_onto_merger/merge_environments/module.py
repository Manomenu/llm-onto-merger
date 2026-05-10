from pydantic import BaseModel
from rdflib import Graph

from llm_onto_merger.extract_environments.merge_environment import MergeEnvironment
from llm_onto_merger.logger import get_logger
from llm_onto_merger.ontology import Entity, entities_to_graph

from .agent import merge_agent

log = get_logger(__name__)


class MergedOntology(BaseModel):
    Merged_Ontology: list[Entity]


_MERGED_ONTOLOGY_SCHEMA = MergedOntology.model_json_schema()
_INSTRUCTION_LEN = len(merge_agent.default_options.get("instructions") or "")


class MergeEnvironmentsModule:
    async def merge(self, merge_environment: MergeEnvironment) -> Graph:
        request = merge_environment.to_string()
        log.info(
            "Sending merge request | instruction: %d chars | request: %d chars | total: %d chars",
            _INSTRUCTION_LEN,
            len(request),
            _INSTRUCTION_LEN + len(request),
        )
        response = await merge_agent.run(
            request,
            options={"response_format": _MERGED_ONTOLOGY_SCHEMA},
        )
        merged = MergedOntology.model_validate(response.value)
        log.info("Received %d entities in merged ontology", len(merged.Merged_Ontology))
        return entities_to_graph(merged.Merged_Ontology)
