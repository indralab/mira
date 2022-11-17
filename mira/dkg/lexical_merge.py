"""A script to propose equivalent nodes in the DKG that aren't already mapped."""

from typing import List

import bioregistry
from mira.dkg.construct import NODES_PATH
import pandas as pd
from tqdm import tqdm
import networkx as nx
from collections import defaultdict
from mira.dkg.utils import PREFIXES
import biomappings
from gilda.grounder import Grounder, ScoredMatch
from mira.dkg.construct import GILDA_TERMS_PATH

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
                (
                    curie,
                    name,
                    term.get_curie(),
                    term.entry_name,
                )
            )
    odf = pd.DataFrame(
        rows, columns=["curie", "name", "xref_curie", "xref_name"]
    )
    odf.to_csv("/Users/cthoyt/Desktop/lexical.tsv", sep="\t", index=False)


if __name__ == "__main__":
    main()
