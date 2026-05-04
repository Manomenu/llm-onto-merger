from pathlib import Path

from owlready2 import Ontology, get_ontology

from .logger import get_logger

log = get_logger(__name__)


def create_ontology(ontology_path: Path) -> Ontology:
    """Load an OWL ontology from the given path."""
    iri = f"file://{Path(ontology_path).resolve()}"
    log.info("Loading ontology from %s", iri)
    onto = get_ontology(iri).load()
    log.info("Ontology loaded: %s", onto.base_iri)
    return onto
