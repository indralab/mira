"""Construct a lossy export of the MIRA DKG in RDF."""

import csv
import gzip

import click
import rdflib
from rdflib import DC, DCTERMS, FOAF, OWL, RDF, RDFS, SKOS, Literal, Namespace
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from mira.dkg.askemo.api import REFERENCED_BY_LATEX, REFERENCED_BY_SYMBOL
from mira.dkg.construct import DEMO_MODULE, EDGES_PATH, NODES_PATH, upload_s3

RDF_TTL_PATH = DEMO_MODULE.join(name="dkg.ttl.gz")

NAMESPACES = {
    "owl": OWL,
    "dc": DC,
    "dcterms": DCTERMS,
    "rdf": RDF,
    "rdfs": RDFS,
    "skos": SKOS,
    "foaf": FOAF,
    "askemo": Namespace("https://indralab.github.io/mira/ontology/"),
}
SKIP_XREFS = {
    # Should be fixed in https://github.com/geneontology/go-ontology/pull/24148
    # and after HP re-imports GO
    "doi:10.1002/(SICI)1097-4687(199608)229:2<121::AID-JMOR1>3.0.CO;2-4",
}
REMAPPING = {
    REFERENCED_BY_SYMBOL: "debio:0000030",
    REFERENCED_BY_LATEX: "debio:0000031",
}


def _ref(s: str):
    if s in REMAPPING:
        s = REMAPPING[s]
    prefix, identifier = s.split(":", 1)
    namespace = NAMESPACES.get(prefix)
    if namespace:
        return namespace[identifier]
    return rdflib.URIRef(f"https://bioregistry.io/{s}")


def _construct_rdf(upload: bool):
    graph = rdflib.Graph()
    for prefix, namespace in NAMESPACES.items():
        graph.namespace_manager.bind(prefix, namespace)

    prefixes = {"bioregistry"}
    with gzip.open(NODES_PATH, "rt") as file:
        reader = csv.reader(file, delimiter="\t")
        _header = next(reader)
        it = tqdm(reader, unit="node", unit_scale=True)
        for (
            curie,
            _label,
            name,
            synoynms,
            _obsolete,
            _type,
            description,
            xrefs,
            alts,
            version,
            # TODO do something with these when we can assert they are CURIEs
            _property_predicates,
            _property_values,
            xref_types,
            synonym_types,
            _sources,
        ) in it:
            if not curie or curie.startswith("_:geni"):
                continue
            if curie in SKIP_XREFS:
                tqdm.write(f"skipping bad curie: {curie}")
                continue
            prefix, identifier = curie.split(":", 1)
            prefixes.add(prefix)
            try:
                uri = _ref(curie)
            except AttributeError as e:
                tqdm.write(f"Error on {curie}: {e} from ")
                continue
            if name:
                graph.add((uri, _ref("rdfs:label"), Literal(name)))
            graph.add((uri, _ref("rdfs:isDefinedBy"), _ref(f"bioregistry:{prefix}")))
            if version:
                graph.add((uri, DCTERMS.hasVersion, Literal(version)))
            if description:
                graph.add((uri, _ref("dcterms:description"), Literal(description)))
            for synonym, synonym_pred_curie in zip(synoynms.split(";"), synonym_types.split(";")):
                if synonym:
                    graph.add((uri, _ref(synonym_pred_curie), Literal(synonym)))
            for xref_curie, xref_pred_curie in zip(xrefs.split(";"), xref_types.split(";")):
                if xref_curie:
                    if xref_curie in SKIP_XREFS:
                        tqdm.write(f"{curie} got disallowed xref: {xref_curie}")
                        continue
                    graph.add((uri, _ref(xref_pred_curie), _ref(xref_curie)))
                    prefixes.add(xref_curie.split(":", 1)[0])
            for alt_curie in alts.split(";"):
                if alt_curie:
                    if xref_curie in SKIP_XREFS:
                        tqdm.write(f"{curie} got disallowed alt: {alt_curie}")
                        continue
                    graph.add((uri, _ref("iao:0000118"), _ref(alt_curie)))

    # prefixes.difference_update(prefix for prefix, _ in graph.namespaces())
    for prefix in prefixes:
        if prefix not in NAMESPACES:
            graph.bind(prefix, rdflib.Namespace(f"https://bioregistry.io/{prefix}:"))

    with gzip.open(EDGES_PATH, "rt") as file:
        reader = csv.reader(file, delimiter="\t")
        _header = next(reader)
        it = tqdm(reader, unit="edge", unit_scale=True)
        for s, o, _type, p, _source, _graph, _version in it:
            if s.startswith("http"):
                continue  # skip unnormalized
            if o in SKIP_XREFS:
                tqdm.write(f"triple with bad values: {s} {p} {o}")
                continue
            p_ref = rdflib.URIRef(p) if p.startswith("http") else _ref(p)
            graph.add((_ref(s), p_ref, _ref(o)))

    tqdm.write("serializing to turtle")
    with gzip.open(RDF_TTL_PATH, "wb") as file:
        graph.serialize(file, format="turtle")
    tqdm.write("done")

    if upload:
        upload_s3(RDF_TTL_PATH)


@click.command()
@click.option("--upload", is_flag=True)
def main(upload: bool):
    """Create an RDF dump and upload to S3."""
    with logging_redirect_tqdm():
        _construct_rdf(upload)


if __name__ == "__main__":
    main()
