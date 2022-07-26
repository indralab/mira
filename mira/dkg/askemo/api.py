import json
from pathlib import Path
from typing import List, Mapping, Optional

from pydantic import BaseModel, Field

from mira.dkg.models import EntityType, Synonym, Xref

HERE = Path(__file__).parent.resolve()
ONTOLOGY_PATH = HERE.joinpath("askemo.json")

#: Valid equivalence annotions in ASKEMO
EQUIVALENCE_TYPES = {
    "skos:exactMatch",
    "skos:relatedMatch",
    "skos:narrowMatch",
    "skos:broadBarch",
    # Don't include these since they are lower specificity
    #  "oboinowl:hasDbXref",
    #  "owl:equivalentTo",
}

REFERENCED_BY_LATEX = "referenced_by_latex"
REFERENCED_BY_SYMBOL = "referenced_by_symbol"

#: Keys are values in ASKEMO and values are OBO specificities
SYNONYM_TYPES = {
    "oboInOwl:hasExactSynonym": "EXACT",
    "oboInOwl:hasBroadSynonym": "BROAD",
    "oboInOwl:hasNarrowSynonym": "NARROW",
    "oboInOwl:hasRelatedSynonym": "RELATED",
    REFERENCED_BY_LATEX: "RELATED",
    REFERENCED_BY_SYMBOL: "RELATED",
    # Don't include these since they are lower specificity
    # "oboInOwl:hasSynonym": "RELATED",
}


class Term(BaseModel):
    # TODO combine with dkg.client.Entity class

    id: str
    name: str
    type: EntityType
    obsolete: bool = Field(default=False)
    description: str
    xrefs: List[Xref] = Field(default_factory=list)
    parents: List[str] = Field(default_factory=list, description="A list of CURIEs for parent terms")
    synonyms: List[Synonym] = Field(default_factory=list)
    physical_min: Optional[float] = None
    physical_max: Optional[float] = None
    suggested_data_type: Optional[str] = None
    suggested_unit: Optional[str] = None
    typical_min: Optional[float] = None
    typical_max: Optional[float] = None

    @property
    def prefix(self) -> str:
        """Get the prefix for the term."""
        return self.id.split(":", 1)[0]


def get_askemo_terms() -> Mapping[str, Term]:
    """Load the ontology JSON."""
    rv = {}
    for obj in json.loads(ONTOLOGY_PATH.read_text()):
        term = Term.parse_obj(obj)
        rv[term.id] = term
    return rv


def write(ontology: Mapping[str, Term]) -> None:
    terms = [
        term.dict(exclude_unset=True, exclude_defaults=True, exclude_none=True)
        for _curie, term in sorted(ontology.items())
    ]
    ONTOLOGY_PATH.write_text(
        json.dumps(terms, sort_keys=True, ensure_ascii=False, indent=2)
    )


def lint():
    write(get_askemo_terms())


if __name__ == "__main__":
    lint()
