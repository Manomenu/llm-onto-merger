import itertools
import string

from agent_framework.ollama import OllamaChatClient
from agent_framework_openai import OpenAIChatClient
from rdflib import OWL, RDF, RDFS

from ..extract_environments.merge_environment import MERGED_CODE
from ..settings import settings

_RDF_NS = str(RDF)
_RDFS_NS = str(RDFS)
_OWL_NS = str(OWL)


def _ensure_code(ns: str, ns_to_code: dict[str, str], code_to_ns: dict[str, str]) -> str:
    """Return code for ns, allocating a fresh one (and updating both maps) if absent.

    The fresh code follows the same scheme as build_namespace_codec: shortest
    available alphabetic combination of length 2+, skipping MERGED_CODE.
    """
    if ns in ns_to_code:
        return ns_to_code[ns]
    for length in itertools.count(2):
        for combo in itertools.product(string.ascii_lowercase, repeat=length):
            code = "".join(combo)
            if code != MERGED_CODE and code not in code_to_ns:
                ns_to_code[ns] = code
                code_to_ns[code] = ns
                return code
    raise RuntimeError("unreachable: code generator exhausted")


def _build_instructions(ns_to_code: dict[str, str], code_to_ns: dict[str, str]) -> str:
    rdf = _ensure_code(_RDF_NS, ns_to_code, code_to_ns)
    rdfs = _ensure_code(_RDFS_NS, ns_to_code, code_to_ns)
    owl = _ensure_code(_OWL_NS, ns_to_code, code_to_ns)

    return f"""
        You are responsible for merging two ontologies (Ontology_1 and Ontology_2).
        **You are a domain expert in both fields that Ontology_1 and Ontology_2 cover, so you have deep understanding of concepts and relations in both ontologies.
        You focus on enhancing resulting ontology, by creating new cross-ontology relations, merging redundant entities into a single entity, and fixing domain inconsistencies.**

        Both ontologies are represented as a list of entity instances.
        Entity structure is presented below.

        Your task is to analyze both ontologies and alignments (Alignments) that
        represent mandatory merges into a single entity between entities from both ontologies.
        (That means, all triples should be assingled to one of the merged entities and have alias property of th merged entity.)
        After that, you should only return single ontology (Merged_Ontology), that should meet as much good ontology
        qualities as possible. That said, it should be as good in given metrics as possible:

        Structural coherence
        - no logical inconsistencies should be created in Merged_Ontology. For example, a class cannot be a subclass of two disjoint classes.
        - Every named class in Merged_Ontology MUST have at least one explicit `{rdfs}::subClassOf` parent. There must be no orphan classes.
        - get rid of is-a cycles if they exist, because it would mean, that none of such classes can have instances.

        Domain coherence
        - all rules/relations that domain experts would experts would expect to be true should be true in merged ontology
        and all rules that domain experts would expect to be false should be removed from merged ontology.
        For example, if in Ontology_1 we have a class "Person" with a property "hasAge" and in Ontology_2 we have a class "Car" with a property "hasAge",
        merged ontology should not allow for an entity to be both a "Person" and a "Car" at the same time, because it would lead to domain inconsistency.
        Anoter example would be removing is-a relation between "Surgery" intance and "Plant" class.
        - Do not add more than twice the number of `{owl}::disjointWith` assertions already present in the input ontologies. Adding many disjoint pairs without strong domain justification is an anti-pattern that creates false constraints and makes the ontology over-restrictive.

        Cross-ontology and intra-ontology relations / Knowledge completeness
        - Merged_Ontology can and should introduce new relations between entities from the same ontology when those relations are implied by domain knowledge but were not explicitly stated.
        For example, if Ontology_1 has class "Animal" and class "Dog" without a `{rdfs}::subClassOf` relation between them, merged ontology should introduce ('Dog', '{rdfs}::subClassOf', 'Animal') because it is a universally known domain fact.
        Do not invent relations that are not grounded in domain knowledge — for example, do not introduce is-a between "Cat" and "Dog" just because both exist in the same ontology.
        - Merged_Ontology MUST introduce new relations between entities from different ontologies (cross-ontology relations) whenever they are domain-justified. This is the important purpose of merging.
        For every pair of classes (A from Ontology_1, B from Ontology_2) where A is a specialization of B (or vice versa) based on domain knowledge, you MUST add the corresponding `{rdfs}::subClassOf` triple. For example, "Animal" in Ontology_1 and "Cat" in Ontology_2 → add ('Cat', '{rdfs}::subClassOf', 'Animal').
        For example, a pair of classes that share domain-relevant relations beyond `{rdfs}::subClassOf` (part-of, member-of, has-property), can have the corresponding object/data properties introduced.
        A merge that produces no cross-ontology relations beyond the input alignments is a failure — at minimum, the alignment-implied connections must be transitively extended.

        Conciseness
        - No two entities in Merged_Ontology should share the same local name. If two entities from different ontologies have the same local name, you must either:
          (a) merge them into one entity (if they represent the same concept), adding alias triples for the replaced URIs, or
          (b) rename one of them to a more precise name that distinguishes it from the other.
        - Each relation, entity is unique in Merged_Ontology. For example, if we had "Underaged" class in Ontology_1 and "Child" class in Ontology_2 it should exist in Merged_Ontology as one class,
        with name that is more suitable for the domain and have all information from both "Underaged" and "Child" classes.
        - No duplicate names for axioms. For example, if we have "hasAge" property in Ontology_1 and "ageValue" property in Ontology_2,
        then Merged_Ontology should contain only one property with name that is more suitable for the domain.
        - Whenever you merge two entities into one (i.e. an entity from Ontology_1 and an entity from Ontology_2 are replaced by a single entity in Merged_Ontology),
        you MUST add an alias triple for every replaced entity URI using the predicate zz::alias.
        STRICT FORMAT: the alias object MUST be exactly `oldcode;;LocalName` — the separator is ";;" (two semicolons), NOT "::", and NO extra text, spaces, or explanations.
        CORRECT:   ('ab::Child', 'zz::alias', 'aa;;Underaged')
        INCORRECT: ('ab::Child', 'zz::alias', 'Alias for aa::Underaged to preserve reference.')
        INCORRECT: ('ab::Child', 'zz::alias', 'aa::Underaged')

        Knowledge preservation (Accuracy)
        - Merged_Ontology should contain as much information from Ontology_1 and Ontology_2 as possible.
        For example, if Ontology_2 contains class "Surgery" with property "hasComplication",
        Merged_Ontology should either contain those entities or have transformed representation of that information.
        If Ontology_2 contained "MedicalSurgery" class and only "MedicalSurgery" class remains in Merged_Ontology
        it is alright, because it is a transformed representation of "Surgery" class.
        It would be even better if "MedicialSurgery" class has added "alias" property to "Surgery".
        - CRITICAL: preserve complex OWL axiom structures exactly as they appear in the inputs:
          * `{rdf}::type {owl}::Class` and `{rdf}::type {owl}::ObjectProperty`/`{owl}::DatatypeProperty` declarations — do not strip type declarations when restructuring the hierarchy.

        Hierarchy integration quality
        - Merged_Ontology is of higher quality if there is more "is-a" relations between entities from Ontology_1 and Ontology_2 in Merged_Ontology.
        - Prefer deep hierarchies over flat ones: where domain knowledge supports it, introduce intermediate classes so the average path
          from root to a leaf is longer (a hierarchy with depth 3-4 is generally better than depth 1).

        Understandability
        - Every class and property in Merged_Ontology MUST have an `{rdfs}::comment`. No entity may appear in Merged_Ontology without one.
        - If the source ontology already provides a comment, preserve it (or improve it). If it does not, you MUST add one based on your domain knowledge — a short description of what the entity represents (e.g. "A surgical procedure performed for medical purposes").
        - Every class and property should also have an `{rdfs}::label` with a human-readable name (e.g. "Medical Surgery"). If the source already provides one, preserve it; otherwise add one.

        Besides good ontology qualities merged ontology should also meet other mandatory
        requirements related to Border_1 and Border_2:
        - Merged_Ontology should contain a relation to/from every entity from Border_1 and Border_2.
        - You can modify relations, create more of them, but need to keep border entites in a relation.
        - Border entity names should be preserved in Merged_Ontology, do not change their URIs also.
        """


def build_merge_agent(ns_to_code: dict[str, str], code_to_ns: dict[str, str]):
    """Construct the merge agent with namespace codes substituted into instructions.

    The codec assigns short codes to all namespaces in the data plus the
    well-known set (rdf/rdfs/owl/xsd/...).  Because the per-request prompt
    serialises every URI as `code::LocalName`, the instructions must reference
    predicates the same way — otherwise the LLM sees `rdfs:comment` in the
    instructions but emits triples in the `code::` format and predicate URIs
    diverge.  This factory builds an agent whose instructions use the actual
    codes from this run's codec.

    Mutates both ns_to_code and code_to_ns if rdf/rdfs/owl namespaces are
    missing — they will be assigned fresh codes so the serializer/deserializer
    stay in sync with the instructions.
    """
    instructions = _build_instructions(ns_to_code, code_to_ns)
    client = (
        OpenAIChatClient(
            model=settings.vllm_model, api_key="Empty", base_url=settings.vllm_host
        )
        if settings.use_vllm
        else OllamaChatClient(
            host=settings.ollama_host,
            model=settings.ollama_model,
        )
    )
    return client.as_agent(
        name="Ontology Merger Agent",
        instructions=instructions,
    )
