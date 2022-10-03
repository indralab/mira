"""
Generate the nodes and edges file for the MIRA domain knowledge graph.

After these are generated, see the /docker folder in the repository for loading
a neo4j instance.

Example command for local bulk import:

.. code::

    neo4j-admin import --delimiter='TAB' \
        --force \
        --database=mira \
        --skip-duplicate-nodes=true \
        --skip-bad-relationships=true \
        --nodes ~/.data/mira/demo/import/nodes.tsv.gz \
        --relationships ~/.data/mira/demo/import/edges.tsv.gz
"""

import csv
import gzip
import itertools as itt
import json
from collections import Counter
from datetime import datetime
from operator import methodcaller
from pathlib import Path
from typing import Dict, NamedTuple, Sequence, Union

import bioontologies
import bioregistry
import click
import pystow
from bioontologies import obograph
from tabulate import tabulate
from tqdm import tqdm

from mira.constants import EDGE_HEADER, MODULE, NODE_HEADER
from mira.dkg.utils import PREFIXES

MODULE = pystow.module("mira")
DEMO_MODULE = MODULE.module("demo", "import")
EDGE_NAMES_PATH = DEMO_MODULE.join(name="relation_info.json")
UNSTANDARDIZED_NODES_PATH = DEMO_MODULE.join(name="unstandardized_nodes.tsv")
UNSTANDARDIZED_EDGES_PATH = DEMO_MODULE.join(name="unstandardized_edges.tsv")
SUB_EDGE_COUNTER_PATH = DEMO_MODULE.join(name="count_subject_prefix_predicate.tsv")
SUB_EDGE_TARGET_COUNTER_PATH = DEMO_MODULE.join(
    name="count_subject_prefix_predicate_target_prefix.tsv"
)
EDGE_OBJ_COUNTER_PATH = DEMO_MODULE.join(name="count_predicate_object_prefix.tsv")
EDGE_COUNTER_PATH = DEMO_MODULE.join(name="count_predicate.tsv")
NODES_PATH = DEMO_MODULE.join(name="nodes.tsv.gz")
EDGES_PATH = DEMO_MODULE.join(name="edges.tsv.gz")
METAREGISTRY_PATH = DEMO_MODULE.join(name="metaregistry.json")
OBSOLETE = {"oboinowl:ObsoleteClass", "oboinowl:ObsoleteProperty"}
EDGES_PATHS: Dict[str, Path] = {
    prefix: DEMO_MODULE.join("sources", name=f"edges_{prefix}.tsv") for prefix in PREFIXES
}
LABELS = {
    "http://www.w3.org/2000/01/rdf-schema#isDefinedBy": "is defined by",
    "rdf:type": "type",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": "type",
    # FIXME deal with these relations
    "http://purl.obolibrary.org/obo/uberon/core#proximally_connected_to": "proximally_connected_to",
    "http://purl.obolibrary.org/obo/uberon/core#extends_fibers_into": "proximally_connected_to",
    "http://purl.obolibrary.org/obo/uberon/core#channel_for": "proximally_connected_to",
    "http://purl.obolibrary.org/obo/uberon/core#distally_connected_to": "proximally_connected_to",
    "http://purl.obolibrary.org/obo/uberon/core#channels_into": "channels_into",
    "http://purl.obolibrary.org/obo/uberon/core#channels_from": "channels_from",
    "http://purl.obolibrary.org/obo/uberon/core#subdivision_of": "subdivision_of",
    "http://purl.obolibrary.org/obo/uberon/core#protects": "protects",
    "http://purl.obolibrary.org/obo/uberon/core#posteriorly_connected_to": "posteriorly_connected_to",
    "http://purl.obolibrary.org/obo/uberon/core#evolved_from": "evolved_from",
    "http://purl.obolibrary.org/obo/uberon/core#anteriorly_connected_to": "anteriorly_connected_to",
}

DEFAULT_VOCABS = [
    "oboinowl",
    "ro",
    "bfo",
    "owl",
    "rdfs",
    "bspo",
    # "gorel",
    "iao",
    # "sio",
    "omo",
    "debio",
]


class NodeInfo(NamedTuple):
    curie: str
    prefix: str
    label: str
    synonyms: str
    deprecated: str
    type: str
    definition: str
    xrefs: str
    alts: str
    version: str


@click.command()
@click.option(
    "--add-xref-edges",
    is_flag=True,
    help="Add edges for xrefs to external ontology terms",
)
@click.option("--summaries", is_flag=True, help="Print summaries of nodes and edges while building")
@click.option("--do-upload", is_flag=True, help="Upload to S3 on completion")
def main(add_xref_edges: bool, summaries: bool, do_upload: bool):
    """Generate the node and edge files."""
    if EDGE_NAMES_PATH.is_file():
        edge_names = json.loads(EDGE_NAMES_PATH.read_text())
    else:
        edge_names = {}
        for edge_prefix in DEFAULT_VOCABS:
            click.secho(f"Caching {bioregistry.get_name(edge_prefix)}", fg="green", bold=True)
            parse_results = bioontologies.get_obograph_by_prefix(edge_prefix)
            for edge_graph in parse_results.graph_document.graphs:
                edge_graph = edge_graph.standardize()
                for edge_node in edge_graph.nodes:
                    if edge_node.deprecated or edge_node.id.startswith("_:genid"):
                        continue
                    if not edge_node.lbl:
                        if edge_node.id in LABELS:
                            edge_node.lbl = LABELS[edge_node.id]
                        elif edge_node.prefix:
                            edge_node.lbl = edge_node.luid
                        else:
                            click.secho(f"missing label for {edge_node.curie}")
                            continue
                    if not edge_node.prefix:
                        tqdm.write(f"unparsable IRI: {edge_node.id} - {edge_node.lbl}")
                        continue
                    edge_names[edge_node.curie] = edge_node.lbl.strip()
        EDGE_NAMES_PATH.write_text(json.dumps(edge_names, sort_keys=True, indent=2))

    nodes: Dict[str, NamedTuple] = {}
    unstandardized_nodes = []
    unstandardized_edges = []
    edge_usage_counter = Counter()
    subject_edge_usage_counter = Counter()
    subject_edge_target_usage_counter = Counter()
    edge_target_usage_counter = Counter()

    def _get_edge_name(curie_: str, strict: bool = False) -> str:
        if curie_ in LABELS:
            return LABELS[curie_]
        elif curie_ in edge_names:
            return edge_names[curie_]
        elif curie_ in nodes:
            return nodes[curie_][2]
        elif strict:
            raise ValueError(
                f"Can not infer name for edge curie: {curie_}. Add an entry to the LABELS dictionary"
            )
        else:
            return curie_

    for prefix in PREFIXES:
        edges = []

        parse_results = bioontologies.get_obograph_by_prefix(prefix)
        if parse_results.graph_document is None:
            click.secho(
                f"{bioregistry.get_name(prefix)} has no graph document",
                fg="red",
                bold=True,
            )
            continue

        _graphs = parse_results.graph_document.graphs
        click.secho(
            f"{bioregistry.get_name(prefix)} ({len(_graphs)} graphs)", fg="green", bold=True
        )

        for graph in tqdm(_graphs, unit="graph", desc=prefix):
            graph: obograph.Graph = graph.standardize(tqdm_kwargs=dict(leave=False))
            if not graph.id:
                raise ValueError(f"graph in {prefix} missing an ID")
            version = graph.version
            if version == "imports":
                version = None
            for node in graph.nodes:
                if node.deprecated or not node.type or not node.prefix or not node.luid:
                    continue
                if node.id.startswith("_:gen"):  # skip blank nodes
                    continue
                try:
                    curie = node.curie
                except ValueError:
                    tqdm.write(f"error parsing {node.id}")
                    continue
                if node.curie.startswith("_:gen"):
                    continue
                if curie not in nodes or (curie in nodes and prefix == node.prefix):
                    nodes[curie] = NodeInfo(
                        node.curie,
                        node.prefix,
                        node.lbl.strip('"').strip().strip('"').replace("\n", " ").replace("  ", " ")
                        if node.lbl
                        else "",
                        ";".join(synonym.val for synonym in node.synonyms),
                        "true" if node.deprecated else "false",
                        node.type.lower(),
                        (node.definition or "")
                        .replace('"', "")
                        .replace("\n", " ")
                        .replace("  ", " "),
                        ";".join(xref.curie for xref in node.xrefs if xref.prefix),
                        ";".join(node.alternative_ids),
                        version or "",
                    )

                if node.replaced_by:
                    edges.append(
                        (
                            node.replaced_by,
                            node.curie,
                            "replaced_by",
                            "iao:0100001",
                            prefix,
                            graph.id,
                            version or "",
                        )
                    )
                    if node.replaced_by not in nodes:
                        nodes[node.replaced_by] = NodeInfo(
                            node.replaced_by,
                            node.replaced_by.split(":", 1)[0],
                            "",  # label
                            "",  # synonyms
                            "true",  # deprecated
                            "CLASS",  # type
                            "",  # definition
                            "",  # xrefs
                            "",  # alts
                            "",  # version
                        )

                if add_xref_edges:
                    for xref in node.xrefs:
                        try:
                            xref_curie = xref.curie
                        except ValueError:
                            continue
                        if xref_curie.split(":", 1)[0] in obograph.PROVENANCE_PREFIXES:
                            # Don't add provenance information as xrefs
                            continue
                        edges.append(
                            (
                                node.curie,
                                xref.curie,
                                "xref",
                                "oboinowl:hasDbXref",
                                prefix,
                                graph.id,
                                version or "",
                            )
                        )
                        if xref_curie not in nodes:
                            nodes[xref_curie] = NodeInfo(
                                xref.curie,
                                xref.prefix,
                                "",  # label
                                "",  # synonyms
                                "false",  # deprecated
                                "CLASS",  # type
                                "",  # definition
                                "",  # xrefs
                                "",  # alts
                                "",  # version
                            )

                for provenance_curie in node.get_provenance():
                    if provenance_curie not in nodes:
                        nodes[provenance_curie] = NodeInfo(
                            curie=provenance_curie,
                            prefix=provenance_curie.split(":")[0],
                            label="",
                            synonyms="",
                            deprecated="false",
                            type="CLASS",
                            definition="",
                            xrefs="",
                            alts="",
                            version="",  # version
                        )
                    edges.append(
                        (
                            node.curie,
                            provenance_curie,
                            "has_citation",
                            "debio:0000029",
                            prefix,
                            graph.id,
                            version or "",
                        )
                    )

            if summaries:
                counter = Counter(node.prefix for node in graph.nodes)
                tqdm.write(
                    "\n"
                    + tabulate(
                        [
                            (k, count, bioregistry.get_name(k) if k is not None else "")
                            for k, count in counter.most_common()
                        ],
                        headers=["prefix", "count", "name"],
                        tablefmt="github",
                        # intfmt=",",
                    )
                )
                edge_counter = Counter(edge.pred for edge in graph.edges)
                tqdm.write(
                    "\n"
                    + tabulate(
                        [
                            (pred_curie, count, _get_edge_name(pred_curie, strict=True))
                            for pred_curie, count in edge_counter.most_common()
                        ],
                        headers=["predicate", "count", "name"],
                        tablefmt="github",
                        # intfmt=",",
                    )
                    + "\n"
                )

            unstandardized_nodes.extend(node.id for node in graph.nodes if not node.prefix)
            unstandardized_edges.extend(
                edge.pred for edge in graph.edges if edge.pred.startswith("http")
            )

            edges.extend(
                (
                    edge.sub,
                    edge.obj,
                    _get_edge_name(edge.pred).lower().replace(" ", "_").replace("-", "_"),
                    edge.pred,
                    prefix,
                    graph.id,
                    version or "",
                )
                for edge in tqdm(
                    sorted(graph.edges, key=methodcaller("as_tuple")), unit="edge", unit_scale=True
                )
                if edge.obj not in OBSOLETE
            )

        for sub, obj, pred_label, pred, *_ in edges:
            edge_target_usage_counter[pred, pred_label, obj.split(":")[0]] += 1
            subject_edge_usage_counter[sub.split(":")[0], pred, pred_label] += 1
            subject_edge_target_usage_counter[
                sub.split(":")[0], pred, pred_label, obj.split(":")[0]
            ] += 1
            edge_usage_counter[pred, pred_label] += 1

        edges_path = EDGES_PATHS[prefix]
        with edges_path.open("w") as file:
            writer = csv.writer(file, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(EDGE_HEADER)
            writer.writerows(edges)
        tqdm.write(f"output edges to {edges_path}")

    with gzip.open(NODES_PATH, "wt") as file:
        writer = csv.writer(file, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(NODE_HEADER)
        writer.writerows(
            (node for _curie, node in tqdm(sorted(nodes.items()), unit="node", unit_scale=True))
        )
    tqdm.write(f"output edges to {NODES_PATH}")

    # CAT edge files together
    with gzip.open(EDGES_PATH, "wt") as file:
        writer = csv.writer(file, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(EDGE_HEADER)
        for prefix, edge_path in tqdm(sorted(EDGES_PATHS.items()), desc="cat edges"):
            with edge_path.open() as edge_file:
                reader = csv.reader(edge_file, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
                _header = next(reader)
                writer.writerows(reader)

    unstandardized_nodes_counter = Counter(unstandardized_nodes)
    _write_counter(UNSTANDARDIZED_NODES_PATH, unstandardized_nodes_counter, title="url")

    unstandardized_edges_counter = Counter(unstandardized_edges)
    _write_counter(UNSTANDARDIZED_EDGES_PATH, unstandardized_edges_counter, title="url")

    _write_counter(
        EDGE_OBJ_COUNTER_PATH,
        edge_target_usage_counter,
        unpack=True,
        title=("predicate", "predicate_label", "object_prefix"),
    )
    _write_counter(
        SUB_EDGE_COUNTER_PATH,
        subject_edge_usage_counter,
        unpack=True,
        title=("subject_prefix", "predicate", "predicate_label"),
    )
    _write_counter(
        SUB_EDGE_TARGET_COUNTER_PATH,
        subject_edge_target_usage_counter,
        unpack=True,
        title=("subject_prefix", "predicate", "predicate_label", "object_prefix"),
    )
    _write_counter(
        EDGE_COUNTER_PATH,
        edge_usage_counter,
        unpack=True,
        title=("predicate", "predicate_label"),
    )

    if do_upload:
        upload_neo4j_s3()

    from .construct_rdf import _construct_rdf

    _construct_rdf(upload=do_upload)

    from .construct_registry import _construct_registry, EPI_CONF_PATH

    _construct_registry(
        config_path=EPI_CONF_PATH,
        output_path=METAREGISTRY_PATH,
        nodes_path=NODES_PATH,
        edges_path=EDGES_PATH,
        upload=do_upload,
    )


def _write_counter(
    path: Path,
    counter: Counter,
    title: Union[None, str, Sequence[str]] = None,
    unpack: bool = False,
) -> None:
    with path.open("w") as file:
        if title:
            if unpack:
                print(*title, "count", sep="\t", file=file)
            else:
                print(title, "count", sep="\t", file=file)
        for key, count in counter.most_common():
            if unpack:
                print(*key, count, sep="\t", file=file)
            else:
                print(key, count, sep="\t", file=file)


def upload_s3(path: Path, *, bucket: str = "askem-mira", s3_client=None) -> None:
    """Upload the nodes and edges to S3."""
    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")

    today = datetime.today().strftime("%Y-%m-%d")
    # don't include a preceding or trailing slash
    key = f"dkg/epi/build/{today}/"
    config = {
        # https://stackoverflow.com/questions/41904806/how-to-upload-a-file-to-s3-and-make-it-public-using-boto3
        "ACL": "public-read",
        "StorageClass": "INTELLIGENT_TIERING",
    }

    s3_client.upload_file(
        Filename=path.as_posix(),
        Bucket=bucket,
        Key=key + path.name,
        ExtraArgs=config,
    )


def upload_neo4j_s3() -> None:
    """Upload the nodes and edges to S3."""
    import boto3

    s3_client = boto3.client("s3")

    paths = [
        UNSTANDARDIZED_EDGES_PATH,
        UNSTANDARDIZED_NODES_PATH,
        NODES_PATH,
        EDGES_PATH,
        SUB_EDGE_COUNTER_PATH,
        SUB_EDGE_TARGET_COUNTER_PATH,
        EDGE_OBJ_COUNTER_PATH,
        EDGE_COUNTER_PATH,
    ]
    for path in tqdm(paths):
        tqdm.write(f"uploading {path}")
        upload_s3(path=path, s3_client=s3_client)


if __name__ == "__main__":
    main()
