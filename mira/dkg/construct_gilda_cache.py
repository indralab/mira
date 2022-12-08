"""Construct a Gilda grounding cache for all terms in the graph."""

import csv
import gzip
from typing import Iterable

import click
import pandas as pd
from gilda.process import normalize
from gilda.term import Term, filter_out_duplicates
from tqdm import tqdm

from mira.dkg.construct import GILDA_TERMS_PATH, NODES_PATH, upload_s3


@click.command()
@click.option("--upload")
def main(upload):
    _main(upload=upload)


def _main(upload: bool):
    terms = filter_out_duplicates(list(_iter_terms()))
    header = [
        "norm_text",
        "text",
        "db",
        "id",
        "entry_name",
        "status",
        "source",
        "organism",
        "source_db",
        "source_id",
    ]
    with gzip.open(GILDA_TERMS_PATH, "wt", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(header)
        writer.writerows(t.to_list() for t in terms)
    if upload:
        upload_s3(GILDA_TERMS_PATH)


def _iter_terms() -> Iterable[Term]:
    df = pd.read_csv(NODES_PATH, sep="\t")
    it = tqdm(df.values, unit_scale=True, unit="node")
    for (
        curie,
        _,
        name,
        synonyms,
        _obsolete,
        _type,
        _description,
        xrefs,
        alts,
        _version,
        _prop_preds,
        _prop_values,
        xref_types,
        synonym_types,
        _sources,
    ) in it:
        if not name or pd.isna(name):
            continue
        prefix, identifier = curie.split(":", 1)
        yield Term(
            norm_text=normalize(name),
            text=name,
            db=prefix,
            id=identifier,
            entry_name=name,
            status="name",
            source=prefix,
        )
        if synonyms and not pd.isna(synonyms):
            for synonym in synonyms.split(";"):
                if not synonym.strip():
                    continue
                yield Term(
                    norm_text=normalize(synonym),
                    text=synonym,
                    db=prefix,
                    id=identifier,
                    entry_name=name,
                    status="synonym",
                    source=prefix,
                )


if __name__ == "__main__":
    main()
