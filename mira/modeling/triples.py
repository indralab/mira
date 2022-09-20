"""Generate knowledge-graph-ready triples from template models."""

import csv
import itertools as itt
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional, Set, Tuple, Union

import bioregistry
from bioregistry import Manager, curie_to_str
from pydantic import BaseModel

from mira.constants import EDGE_HEADER
from mira.metamodel import ControlledConversion, NaturalConversion, Template, \
    TemplateModel
from mira.metamodel.templates import Config
from mira.modeling.base import Generator

if TYPE_CHECKING:
    import pandas

RELATIONS = {
    "ro:0002323": "mereotopologically related to",  # FIXME new relation?
}


class Triple(BaseModel):
    """Represents a triple of 3 CURIEs."""

    sub: str
    pred: str
    obj: str

    def as_tuple(self) -> Tuple[str, str, str]:
        return self.sub, self.pred, self.obj

    def _prefixes(self, manager: Manager) -> Set[str]:
        return {manager.parse_curie(k)[0] for k in (self.sub, self.obj, self.pred)}


class TriplesGenerator(Generator):
    """Generates triples from a templated model to include in the DKG."""

    def __init__(
        self,
        model: TemplateModel,
        manager: Optional[Manager] = None,
        config: Optional[Config] = None,
    ):
        super().__init__(model)
        self.metaregistry = manager or bioregistry.manager
        self.triples = {}
        for template in model.templates:
            for triple in self.iter_triples(template, config=config):
                if triple.sub == triple.obj:
                    continue
                self.triples[triple.as_tuple()] = triple
        self.prefixes = set(
            itt.chain.from_iterable(
                triple._prefixes(self.metaregistry) for triple in self.triples.values()
            )
        )

    def to_dataframe(self) -> "pandas.DataFrame":
        """Get all triples as a pandas dataframe."""
        import pandas

        columns = ["subject", "predicate", "object"]
        df = pandas.DataFrame(
            [t.as_tuple() for t in self.triples.values()],
            columns=columns,
        )
        df = df.drop_duplicates()
        df = df[df["subject"] != df["object"]]
        df = df.sort_values(columns)
        return df

    def write_neo4j_bulk(self, path: Union[str, Path]) -> None:
        """Write a file that can be bulk imported in neo4j."""
        with open(path, "w") as file:
            writer = csv.writer(file, delimiter="\t")
            writer.writerow(EDGE_HEADER)
            writer.writerows(self.iter_neo4j_bulk_rows())

    def iter_neo4j_bulk_rows(self):
        """Iterate over rows that can be written to a neo4j bulk import file."""
        for _, triple in sorted(self.triples.items()):
            yield (
                triple.sub,
                triple.obj,
                RELATIONS[triple.pred],
                triple.pred,
                "template",  # TODO add extra metadata to models?
                "template",
                "",
            )

    def iter_triples(self, template: Template, config: Optional[Config] = None) -> Iterable[Triple]:
        """Iterate triples from a template."""
        if isinstance(template, ControlledConversion):
            for a, b in itt.combinations(
                (template.subject, template.outcome, template.controller), 2
            ):
                yield Triple(
                    sub=curie_to_str(*a.get_curie(config=config)),
                    pred="ro:0002323",  # "related to"
                    obj=curie_to_str(*b.get_curie(config=config)),
                )
        elif isinstance(template, NaturalConversion):
            yield Triple(
                sub=curie_to_str(*template.subject.get_curie(config=config)),
                pred="ro:0002323",  # "related to"
                obj=curie_to_str(*template.outcome.get_curie(config=config)),
            )
        else:
            raise TypeError
