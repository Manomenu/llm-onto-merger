from pydantic import BaseModel
from rdflib import Graph

from llm_onto_merger.extract_environments.merge_environment import MergeEnvironment
from llm_onto_merger.ontology import Entity, entities_to_graph

from .agent import merge_agent


class MergedOntology(BaseModel):
    Merged_Ontology: list[Entity]


_MERGED_ONTOLOGY_SCHEMA = MergedOntology.model_json_schema()


class MergeEnvironmentsModule:
    async def merge(self, merge_environment: MergeEnvironment) -> Graph:
        response = await merge_agent.run(
            merge_environment.to_string(),
            options={"response_format": _MERGED_ONTOLOGY_SCHEMA},
        )
        merged = MergedOntology.model_validate(response.value)
        return entities_to_graph(merged.Merged_Ontology)
