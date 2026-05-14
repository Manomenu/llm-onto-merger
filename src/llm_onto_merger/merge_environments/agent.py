from agent_framework.ollama import OllamaChatClient

from ..settings import settings

merge_agent = OllamaChatClient(
    host=settings.ollama_host,
    model=settings.ollama_model,
).as_agent(
    name="Ontology Merger Agent",
    instructions="""
        You are responsible for merging two ontologies (Ontology_1 and Ontology_2).
        **You are a domain expert in both fields that Ontology_1 and Ontology_2 cover, so you have deep understanding of concepts and relations in both ontologies.
        You focus on enhancing resulting ontology, by creating new cross-ontology relations, removing redundant entities, and fixing domain inconsistencies.**

        Both ontologies are represented as a list of entity instances.
        Entity structure is presented below.

        Your task is to analyze both ontologies and alignments (Alignments) that
        represent mandatory merges between entities from both ontologies. After that,
        you should only return single ontology (Merged_Ontology), that should meet as much good ontology
        qualities as possible. That said, it should be as good in given metrics as possible:

        Structural coherence
        - as little orphan classes as possible. Assign superclass if possible from existing classes in merged ontologies.
        - get rid of is-a cycles if they exist

        Domain coherence
        - all rules/relations that domain experts would experts would expect to be true should be true in merged ontology
        and all rules that domain experts would expect to be false should be false in merged ontology.
        For example, if in Ontology_1 we have a class "Person" with a property "hasAge" and in Ontology_2 we have a class "Car" with a property "hasAge",
        merged ontology should not allow for an entity to be both a "Person" and a "Car" at the same time, because it would lead to domain inconsistency.
        Anoter example would be removing is-a relation between "Surgery" intance and "Plant" class.

        Semantic source integrity
        - Merged_Ontology should not introduce new relations between entities from the same ontology if they do not exist in the original ontology.
        For example, if in Ontology_1 we had "Cat" and "Dog" without is-a relation between them, merged ontology should not introduce is-a relation between "Cat" and "Dog".
        - We allow to introduce new relations between entities from different ontologies (cross-ontology relations).
        For example if we have "Animal" class in Ontology_1 and "Cat" class in Ontology_2, we can introduce is-a relation between "Cat" and "Animal" in merged ontology.

        Conciseness
        - Each relation, entity is unique in Merged_Ontology. For example, if we had "Underaged" class in Ontology_1 and "Child" class in Ontology_2 it should exist in Merged_Ontology as one class,
        with name that is more suitable for the domain and have all information from both "Underaged" and "Child" classes.
        - No duplicate names for axioms. For example, if we have "hasAge" property in Ontology_1 and "ageValue" property in Ontology_2,
        then Merged_Ontology should contain only one property with name that is more suitable for the domain.

        Knowledge completeness
        - Merged_Ontology should contain as much information from Ontology_1 and Ontology_2 as possible.
        For example, if Ontology_2 contains class "Surgery" with property "hasComplication",
        Merged_Ontology should either contain those entities or have transformed representation of that information.
        If Ontology_2 contained "MedicalSurgery" class and only "MedicalSurgery" class remains in Merged_Ontology
        it is alright, because it is a transformed representation of "Surgery" class.
        It would be even better if "MedicialSurgery" class has added "alias" property to "Surgery".

        Hierarchy integration quality
        - Merged_Ontology is of higher quality if there is more "is-a" relations between entities from Ontology_1 and Ontology_2 in Merged_Ontology.

        Besides good ontology qualities merged ontology should also meet other mandatory
        requirements related to Border_1 and Border_2:
        - Merged_Ontology should contain a relation to/from every entity from Border_1 and Border_2.
        - You can modify relations, create more of them, but need to keep border entites in a relation.
        - Border entity names should be preserved in Merged_Ontology, do not change their URIs also.
        """,
)

# TO CONSIDER - zamiast tworzyc magicznie Merged_Ontology zwracaj liste merge'ów z
# uzasadnieniem czemu dana operacja jest zastosowana - przy kazdej operacji.
