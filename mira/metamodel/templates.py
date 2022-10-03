"""
Data models for metamodel templates.

Regenerate the JSON schema by running ``python -m mira.metamodel.templates``.
"""
__all__ = [
    "Concept",
    "Template",
    "Provenance",
    "ControlledConversion",
    "NaturalConversion",
    "NaturalProduction",
    "NaturalDegradation",
    "GroupedControlledConversion",
    "TemplateModel",
    "get_json_schema",
    "templates_equal",
    "assert_concept_context_refinement",
]

import json
import logging
import sys
from collections import ChainMap
from pathlib import Path
from typing import List, Mapping, Optional, Tuple, Literal, Callable, Union

import pydantic
from pydantic import BaseModel, Field

try:
    from typing import Annotated  # py39+
except ImportError:
    from typing_extensions import Annotated


HERE = Path(__file__).parent.resolve()
SCHEMA_PATH = HERE.joinpath("schema.json")

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Config determining how keys are generated"""

    prefix_priority: List[str]


DEFAULT_CONFIG = Config(
    prefix_priority=[
        "ido",
        "ncit",
    ],
)


class Concept(BaseModel):
    """A concept is specified by its identifier(s), name, and - optionally -
    its context.
    """

    name: str = Field(..., description="The name of the concept.")
    identifiers: Mapping[str, str] = Field(
        default_factory=dict, description="A mapping of namespaces to identifiers."
    )
    context: Mapping[str, str] = Field(
        default_factory=dict, description="A mapping of context keys to values."
    )

    def with_context(self, **context) -> "Concept":
        """Return this concept with extra context."""
        return Concept(
            name=self.name,
            identifiers=self.identifiers,
            context=dict(ChainMap(context, self.context)),
        )

    def get_curie(self, config: Optional[Config] = None) -> Tuple[str, str]:
        """Get the priority prefix/identifier pair for this concept."""
        if config is None:
            config = DEFAULT_CONFIG
        if not self.identifiers:
            return "", self.name
        for prefix in config.prefix_priority:
            identifier = self.identifiers.get(prefix)
            if identifier:
                return prefix, identifier
        return tuple(sorted(self.identifiers.items())[0])

    def get_curie_str(self, config: Optional[Config] = None) -> str:
        """Get the priority prefix/identifier as a CURIE string."""
        return ":".join(self.get_curie(config=config))

    def get_key(self, config: Optional[Config] = None):
        return (
            self.get_curie(config=config),
            tuple(sorted(self.context.items())),
        )

    def is_equal_to(self, other: "Concept", with_context: bool = False) -> bool:
        """Test for equality between concepts

        Parameters
        ----------
        other :
            Other Concept to test equality with
        with_context :
            If True, do not consider the two Concepts equal unless they also
            have exactly the same context. If there is no context,
            ``with_context`` has no effect.

        Returns
        -------
        :
            True if ``other`` is the same Concept as this one
        """
        if not isinstance(other, Concept):
            return False

        # With context
        if with_context:
            # Check that the same keys appear in both
            if set(self.context.keys()) != set(other.context.keys()):
                return False

            # Check that the values are the same
            for k1, v1 in self.context.items():
                if v1 != other.context[k1]:
                    return False

        # Check that they are grounded to the same identifier
        if len(self.identifiers) > 0 and len(other.identifiers) > 0:
            if self.get_curie() != other.get_curie():
                return False
            else:
                pass
        # If either or both are ungrounded -> can't know -> False
        else:
            return False

        return True

    def refinement_of(
        self,
        other: "Concept",
        refinement_func: Callable[[str, str], bool],
        with_context: bool = False,
    ) -> bool:
        """Check if this Concept is a more detailed version of another

        Parameters
        ----------
        other :
            The other Concept to compare with. Assumed to be less detailed.
        with_context :
            If True, also consider the context of the Concepts for the
            refinement.
        refinement_func :
            A function that given a source/more detailed entity and a
            target/less detailed entity checks if they are in a child-parent and
            returns a boolean.

        Returns
        -------
        :
            True if this Concept is a refinement of another Concept
        """
        if not isinstance(other, Concept):
            return False

        contextual_refinement = False
        if with_context and assert_concept_context_refinement(
            refined_concept=self, other_concept=other
        ):
            contextual_refinement = True

        # Check if this concept is a child term to other?
        if len(self.identifiers) > 0 and len(other.identifiers) > 0:
            # Check if other is a parent of this concept
            this_curie = ":".join(self.get_curie())
            other_curie = ":".join(other.get_curie())
            ontological_refinement = refinement_func(this_curie, other_curie)

        # Any of them are ungrounded -> cannot know if there is a refinement
        # -> return False
        # len(self.identifiers) == 0 or len(other.identifiers) == 0
        else:
            ontological_refinement = False

        if with_context:
            return ontological_refinement or contextual_refinement
        return ontological_refinement


class Template(BaseModel):
    """The Template is a parent class for model processes"""

    @classmethod
    def from_json(cls, data) -> "Template":
        template_type = data.pop("type")
        stmt_cls = getattr(sys.modules[__name__], template_type)
        return stmt_cls(**data)

    def is_equal_to(self, other: "Template", with_context: bool = False) -> bool:
        """Check if this template is equal to another template

        Parameters
        ----------
        other :
            The other template to check for equality with this one with
        with_context :
            If True, the contexts are taken into account when checking for
            equality. Default: False.

        Returns
        -------
        :
            True if the other Template is equal to this Template
        """
        if not isinstance(other, Template):
            return False
        return templates_equal(self, other, with_context)

    def refinement_of(
        self,
        other: "Template",
        refinement_func: Callable[[str, str], bool],
        with_context: bool = False,
    ) -> bool:
        """Check if this template is a more detailed version of another

        Parameters
        ----------
        other :
            The other template to compare with. Is assumed to be less
            detailed than this template.
        with_context :
            If True, also consider the context of Templates' Concepts for the
            refinement.
        refinement_func :
            A function that given a source/more detailed entity and a
            target/less detailed entity checks if they are in a child-parent
            relationship and returns a boolean.

        Returns
        -------
        :
            True if this Template is a refinement of the other Template.
        """
        if not isinstance(other, Template):
            return False

        if self.type != other.type:
            return False

        for field_name in self.dict(exclude={"type"}):
            this_value = getattr(self, field_name)

            # Check refinement for any attribute that is a Concept; this is
            # strict in the sense that unless every concept of this template is a
            # refinement of the other, the Template as a whole cannot be
            # considered a refinement
            if isinstance(this_value, Concept):
                other_concept = getattr(other, field_name)
                if not this_value.refinement_of(
                    other_concept, refinement_func=refinement_func, with_context=with_context
                ):
                    return False

            elif isinstance(this_value, list):
                if len(this_value) > 0:
                    if isinstance(this_value[0], Provenance):
                        # Skip Provenance
                        continue
                    else:
                        logger.warning(f"Unhandled type List[{type(this_value[0])}]")

            else:
                logger.warning(f"Unhandled type {type(this_value)}")

        return True

    def get_concepts(self):
        """Return the concepts in this template."""
        raise NotImplementedError


class Provenance(BaseModel):
    pass


class ControlledConversion(Template):
    """Specifies a process of controlled conversion from subject to outcome,
    controlled by the controller."""

    type: Literal["ControlledConversion"] = Field("ControlledConversion", const=True)
    controller: Concept
    subject: Concept
    outcome: Concept
    provenance: List[Provenance] = Field(default_factory=list)

    def with_context(self, **context) -> "ControlledConversion":
        """Return a copy of this template with context added"""
        return self.__class__(
            type=self.type,
            subject=self.subject.with_context(**context),
            outcome=self.outcome.with_context(**context),
            controller=self.controller.with_context(**context),
            provenance=self.provenance,
        )

    def get_key(self, config: Optional[Config] = None):
        return (
            self.type,
            self.subject.get_key(config=config),
            self.controller.get_key(config=config),
            self.outcome.get_key(config=config),
        )

    def get_concepts(self):
        """Return the concepts in this template."""
        return [self.controller, self.subject, self.outcome]


class GroupedControlledConversion(Template):
    type: Literal["GroupedControlledConversion"] = Field("GroupedControlledConversion", const=True)
    controllers: List[Concept]
    subject: Concept
    outcome: Concept
    provenance: List[Provenance] = Field(default_factory=list)

    def with_context(self, **context) -> "GroupedControlledConversion":
        """Return a copy of this template with context added"""
        return self.__class__(
            type=self.type,
            controllers=[c.with_context(**context) for c in self.controllers],
            subject=self.subject.with_context(**context),
            outcome=self.outcome.with_context(**context),
            provenance=self.provenance,
        )

    def get_concepts(self):
        """Return the concepts in this template."""
        return self.controllers + [self.subject, self.outcome]


class NaturalConversion(Template):
    """Specifies a process of natural conversion from subject to outcome"""

    type: Literal["NaturalConversion"] = Field("NaturalConversion", const=True)
    subject: Concept
    outcome: Concept
    provenance: List[Provenance] = Field(default_factory=list)

    def with_context(self, **context) -> "NaturalConversion":
        """Return a copy of this template with context added"""
        return self.__class__(
            type=self.type,
            subject=self.subject.with_context(**context),
            outcome=self.outcome.with_context(**context),
            provenance=self.provenance,
        )

    def get_key(self, config: Optional[Config] = None):
        return (
            self.type,
            self.subject.get_key(config=config),
            self.outcome.get_key(config=config),
        )

    def get_concepts(self):
        """Return the concepts in this template."""
        return [self.subject, self.outcome]


class NaturalProduction(Template):
    """A template for the production of a species at a constant rate."""

    type: Literal["NaturalProduction"] = Field("NaturalProduction", const=True)
    outcome: Concept
    provenance: List[Provenance] = Field(default_factory=list)

    def get_concepts(self):
        """Return the concepts in this template."""
        return [self.outcome]


class NaturalDegradation(Template):
    """A template for the degradataion of a species at a proportional rate to its amount."""

    type: Literal["NaturalDegradation"] = Field("NaturalDegradation", const=True)
    subject: Concept
    provenance: List[Provenance] = Field(default_factory=list)

    def get_concepts(self):
        """Return the concepts in this template."""
        return [self.subject]


def get_json_schema():
    """Get the JSON schema for MIRA."""
    rv = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://raw.githubusercontent.com/indralab/mira/main/mira/metamodel/schema.json",
    }
    rv.update(
        pydantic.schema.schema(
            [
                Concept,
                Template,
                *Template.__subclasses__(),
            ],
            title="MIRA Metamodel Template Schema",
            description="MIRA metamodel templates give a high-level abstraction of modeling appropriate for many domains.",
        )
    )
    return rv


def templates_equal(templ: Template, other_templ: Template, with_context: bool) -> bool:
    """Check if two Template objects are equal

    Parameters
    ----------
    templ :
        A template to compare.
    other_templ :
        The other template to compare.
    with_context :
        If True, also check the contexts of the contained Concepts of the
        Template.

    Returns
    -------
    :
        True if the two Template objects are equal.
    """
    if templ.type != other_templ.type:
        return False

    other_dict = other_templ.__dict__
    for key, value in templ.__dict__.items():
        # Already checked type
        if key == "type":
            continue

        if isinstance(value, Concept):
            other_concept: Concept = other_dict[key]
            if not value.is_equal_to(other_concept, with_context=with_context):
                return False

        elif isinstance(value, list):
            if not all(i1 == i2 for i1, i2 in zip(value, other_dict[key])):
                return False
        else:
            raise NotImplementedError(
                f"No comparison implemented for type {type(value)} for Template"
            )
    return True


def assert_concept_context_refinement(refined_concept: Concept, other_concept: Concept) -> bool:
    """Check if one Concept's context is a refinement of another Concept's

    Special case:
    - Both contexts are empty => special case of equal context => False

    Parameters
    ----------
    refined_concept :
        The assumed *more* detailed Concept
    other_concept :
        The assumed *less* detailed Concept

    Returns
    -------
    :
        True if the Concept `refined_concept` truly is strictly more detailed
        than `other_concept`
    """
    refined_context = refined_concept.context
    other_context = other_concept.context
    # 1. False if no context for both
    if len(refined_context) == 0 and len(other_context) == 0:
        return False
    # 2. True if refined concept has context and the other one not
    elif len(refined_context) > 0 and len(other_context) == 0:
        return True
    # 3. False if refined concept does not have context and the other does
    elif len(refined_context) == 0 and len(other_context) > 0:
        return False
    # 4. Both have context
    else:
        # 1. Exactly equal context keys -> False
        # 2. False if refined Concept context is a subset of other context
        #
        # NOTE: issubset is not strict, i.e. is True for equal sets, therefore
        # we need to check for refined.issubset(other) first to be sure that
        # cases 1. and 2. are ruled out when 3. is evaluated
        if set(refined_context.keys()).issubset(other_context.keys()):
            return False

        # 3. Other Concept context is a subset; check equality for the matches
        elif set(other_context.keys()).issubset(refined_context):
            for other_context_key, other_context_value in other_context.items():
                if refined_context[other_context_key] != other_context_value:
                    return False

        # 4. Both Concepts have context, but they are different -> cannot be a
        #    refinement -> False
        elif set(other_context.keys()).symmetric_difference(set(refined_context.keys())):
            return False

        # 5. All cases should be covered, but in case something is missing
        else:
            raise ValueError("Unhandled logic, missing at least one logical option")

    return True


# Needed for proper parsing by FastAPI
SpecifiedTemplate = Annotated[
    Union[
        NaturalConversion, ControlledConversion, NaturalDegradation, NaturalProduction, GroupedControlledConversion,
    ],
    Field(description="Any child class of a Template", discriminator="type"),
]


class TemplateModel(BaseModel):
    templates: List[SpecifiedTemplate] = Field(
        ..., description="A list of any child class of Templates"
    )

    @classmethod
    def from_json(cls, data) -> "TemplateModel":
        templates = [Template.from_json(template) for template in data["templates"]]
        return cls(templates=templates)


class RefinementClosure:
    """A wrapper class for storing a transitive closure and exposing a
    function to check for refinement relationship.

    Typical usage would involve:
    >>> from mira.dkg.client import Neo4jClient
    >>> nc = Neo4jClient()
    >>> rc = RefinementClosure(nc.get_transitive_closure())
    >>> rc.is_ontological_child('doid:0080314', 'bfo:0000016')
    """
    def __init__(self, transitive_closure):
        self.transitive_closure = transitive_closure

    def is_ontological_child(self, child_curie: str, parent_curie: str) -> bool:
        return (child_curie, parent_curie) in self.transitive_closure


def main():
    """Generate the JSON schema file."""
    schema = get_json_schema()
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2))


if __name__ == "__main__":
    main()
