"""Operations for template models."""

import itertools as itt
from typing import Iterable, Mapping, Optional, Set, Tuple, Type

from .templates import *

__all__ = [
    "stratify",
    "model_has_grounding",
    "find_models_with_grounding",
]


def stratify(
    template_model: TemplateModel,
    *,
    key: str,
    strata: Set[str],
    structure: Optional[Iterable[Tuple[str, str]]] = None,
    directed: bool = False,
    conversion_cls: Type[Template] = NaturalConversion,
) -> TemplateModel:
    """Multiplies a model into several strata.

    E.g., can turn the SIR model into a two-city SIR model by splitting each concept into
    two derived concepts, each with the context for one of the two cities

    Parameters
    ----------
    template_model :
        A template model
    key :
        The (singular) name of the stratification, e.g., ``"city"``
    strata :
        A list of the values for stratification, e.g., ``["boston", "nyc"]``
    structure :
        An iterable of pairs corresponding to a directed network structure
        where each of the pairs has two strata. If none given, will assume a complete
        network structure.
    conversion_cls :
        The template class to be used for conversions between strata
        defined by the network structure. Defaults to :class:`NaturalConversion`

    Returns
    -------
    :
        A stratified template model
    """
    if structure is None:
        structure = list(itt.combinations(strata, 2))
        directed = False

    concepts = _get_concepts(template_model)

    templates = []
    # Generate a derived template for each strata
    for stratum, template in itt.product(strata, template_model.templates):
        templates.append(template.with_context(**{key: stratum}))
    # Generate a conversion between each concept of each strata based on the network structure
    for (source_stratum, target_stratum), concept in itt.product(structure, concepts):
        subject = concept.with_context(**{key: source_stratum})
        outcome = concept.with_context(**{key: target_stratum})
        # todo will need to generalize for different kwargs for different conversions
        templates.append(conversion_cls(subject=subject, outcome=outcome))
        if not directed:
            templates.append(conversion_cls(subject=outcome, outcome=subject))
    return TemplateModel(templates=templates)


def _get_concepts(template_model: TemplateModel):
    return list({concept.get_key(): concept for concept in _iter_concepts(template_model)}.values())


def _iter_concepts(template_model: TemplateModel):
    for template in template_model.templates:
        if isinstance(template, ControlledConversion):
            yield from (template.subject, template.outcome, template.controller)
        elif isinstance(template, NaturalConversion):
            yield from (template.subject, template.outcome)
        elif isinstance(template, GroupedControlledConversion):
            yield from template.controllers
            yield from (template.subject, template.outcome)
        elif isinstance(template, NaturalDegradation):
            yield template.subject
        elif isinstance(template, NaturalProduction):
            yield template.outcome
        else:
            raise TypeError(f"could not handle template: {template}")


def model_has_grounding(template_model: TemplateModel, prefix: str,
                        identifier: str) -> bool:
    """Return whether a model contains a given grounding in any role."""
    search_curie = f'{prefix}:{identifier}'
    for template in template_model.templates:
        for concept in template.get_concepts():
            for concept_prefix, concept_id in concept.identifiers.items():
                if concept_prefix == prefix and concept_id == identifier:
                    return True
            for key, curie in concept.context.items():
                if curie == search_curie:
                    return True
    for key, param in template_model.parameters.items():
        for param_prefix, param_id in param.identifiers.items():
            if param_prefix == prefix and param_id == identifier:
                return True
        for key, curie in param.context.items():
            if curie == search_curie:
                return True
    return False


def find_models_with_grounding(template_models: Mapping[str, TemplateModel],
                               prefix: str, identifier: str) -> Mapping[str, TemplateModel]:
    """Filter a dict of models to ones containing a given grounding in any role."""
    return {k: m for k, m in template_models.items()
            if model_has_grounding(m, prefix, identifier)}
