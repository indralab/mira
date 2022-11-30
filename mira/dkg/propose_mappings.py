"""A script to propose equivalent nodes in the DKG that aren't already mapped."""

from collections import defaultdict
from typing import List

import biomappings
import bioregistry
import networkx as nx
import pandas as pd
from biomappings.resources import PredictionTuple, append_prediction_tuples
from gilda.grounder import Grounder, ScoredMatch
from tqdm import tqdm

from mira.dkg.construct import GILDA_TERMS_PATH, NODES_PATH
from mira.dkg.utils import PREFIXES

source_whitelist = {
    "apollosv",
    "idomal",
    "cemo",
    "ido",
    "vo",
    "ovae",
    "oae",
    "cido",
    "covoc",
    "idocovid19",
    "vido",
}

blacklist = {
    "hp",
    "doid",
    "chebi",
    "uberon",
    "ncbitaxon",
    "foaf",
    "uo",
    "oboinowl",
    "owl",
    "rdf",
    "doi",
    "pubmed",
    "pmc",
    "dc",
    "debio",
    "ro",
    "bfo",
    "iao",
}


def main():
    """Propose mappings for curation in Biomappings."""
    imported_prefixes = set(PREFIXES)

    grounder = Grounder(GILDA_TERMS_PATH)

    xref_graph = nx.Graph()
    for mapping in tqdm(
        biomappings.load_mappings(),
        unit_scale=True,
        unit="mapping",
        desc="caching biomappings",
    ):
        source_prefix = mapping["source prefix"]
        target_prefix = mapping["target prefix"]
        if (
            source_prefix not in imported_prefixes
            or target_prefix not in imported_prefixes
        ):
            continue
        xref_graph.add_edge(
            bioregistry.curie_to_str(
                *bioregistry.normalize_parsed_curie(
                    source_prefix,
                    mapping["source identifier"],
                )
            ),
            bioregistry.curie_to_str(
                *bioregistry.normalize_parsed_curie(
                    target_prefix,
                    mapping["target identifier"],
                )
            ),
        )

    xref_prefixes = defaultdict(set)
    df = pd.read_csv(NODES_PATH, sep="\t")

    for curie, xrefs in tqdm(
        df[["id:ID", "xrefs:string[]"]].values,
        unit_scale=True,
        unit="node",
        desc="caching xrefs",
    ):
        if not xrefs or pd.isna(xrefs):
            continue
        for xref in xrefs.split(";"):
            xref_graph.add_edge(curie, xref)
            xref_prefix = xref.split(":")[0]
            if xref_prefix in imported_prefixes:
                xref_prefixes[curie].add(xref_prefix)

    idx = df["name:string"].notna()
    rows = []
    for curie, name in tqdm(
        df[idx][["id:ID", "name:string"]].values,
        unit_scale=True,
        unit="node",
        desc="Matching",
    ):
        prefix, identifier = curie.split(":", 1)
        if prefix not in source_whitelist:
            continue
        scored_matches: List[ScoredMatch] = grounder.ground(name)
        for scored_match in scored_matches:
            term = scored_match.term
            xref_prefix, xref_id = bioregistry.normalize_parsed_curie(
                term.db, term.id
            )
            xref_curie = bioregistry.curie_to_str(xref_prefix, xref_id)
            if prefix == xref_prefix or xref_graph.has_edge(curie, xref_curie):
                continue
            rows.append(
                PredictionTuple(
                    source_prefix=prefix,
                    source_id=identifier,
                    source_name=name,
                    relation="skos:exactMatch",
                    target_prefix=xref_prefix,
                    target_identifier=xref_id,
                    target_name=term.entry_name,
                    type="lexical",
                    confidence=scored_match.score,
                    source="mira",
                )
            )

    append_prediction_tuples(rows)


if __name__ == "__main__":
    main()
