from rdflib import Graph

from llm_onto_merger.extract_environments.merge_environment import MergeEnvironment

from .agent import merge_agent


class MergeEnvironmentsModule:
    async def merge(self, merge_environment: MergeEnvironment) -> Graph:
        response = await merge_agent.run(merge_environment.to_string())
