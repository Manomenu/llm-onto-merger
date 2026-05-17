from rdflib import URIRef


def local_name(uri: URIRef | str) -> str:
    """Return the local fragment of a URI (after # or last /)."""
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]
