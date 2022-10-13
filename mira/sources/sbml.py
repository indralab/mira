"""
Alternate XPath queries for COPASI data:

1. ``copasi:COPASI/rdf:RDF/rdf:Description/bqbiol:hasProperty``
2. ``copasi:COPASI/rdf:RDF/rdf:Description/CopasiMT:is``
"""

import logging
import math
from typing import Iterable, List, Mapping, Optional, Set

import bioregistry
import curies
import sympy
from libsbml import SBMLDocument, SBMLReader
from lxml import etree
from pydantic import BaseModel
from tqdm import tqdm

from mira.metamodel import (
    Concept,
    ControlledConversion,
    GroupedControlledConversion,
    NaturalConversion,
    NaturalDegradation,
    NaturalProduction,
    Template,
)
from mira.metamodel.templates import TemplateModel

__all__ = [
    "ParseResult",
    "template_model_from_sbml_file_path",
    "template_model_from_sbml_file",
    "template_model_from_sbml_string",
    "template_model_from_sbml_document",
    "template_model_from_sbml_model",
]


class TqdmLoggingHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)

logger = logging.getLogger(__name__)
logger.addHandler(TqdmLoggingHandler())


PREFIX_MAP = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dcterms": "http://purl.org/dc/terms/",
    "vCard": "http://www.w3.org/2001/vcard-rdf/3.0#",
    "vCard4": "http://www.w3.org/2006/vcard/ns#",
    "bqbiol": "http://biomodels.net/biology-qualifiers/",
    "bqmodel": "http://biomodels.net/model-qualifiers/",
    "CopasiMT": "http://www.copasi.org/RDF/MiriamTerms#",
    "copasi": "http://www.copasi.org/static/sbml",
}
RESOURCE_KEY = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
#: This XPath query gets annotations on species for their structured
#: identifiers, typically given as MIRIAM URIs or URNs
IDENTIFIERS_XPATH = f"rdf:RDF/rdf:Description/bqbiol:is/rdf:Bag/rdf:li"
#: This is an alternative XPath for groundings that use the isVersionOf
#: relation and are thus less specific than the one above but can be used
#: as fallback
IDENTIFIERS_VERSION_XPATH = f"rdf:RDF/rdf:Description/bqbiol:isVersionOf/rdf:Bag/rdf:li"
#: This XPath query gets annotations on species about their properties,
#: which typically help ad-hoc create subclasses that are more specific
PROPERTIES_XPATH = f"rdf:RDF/rdf:Description/bqbiol:hasProperty/rdf:Bag/rdf:li"
#: This query helps get annotations on reactions, like "this reaction is a
#: _protein-containing complex disassembly_ (GO:0043624)"
IS_VERSION_XPATH = f"rdf:RDF/rdf:Description/bqbiol:hasProperty/rdf:Bag/rdf:li"


class Converter:
    """Wrapper around a curies converter with lazy loading."""
    def __init__(self):
        self.converter = None

    def parse_uri(self, uri):
        if self.converter is None:
            self.converter = curies.Converter.from_reverse_prefix_map(
                bioregistry.manager.get_reverse_prefix_map(include_prefixes=True)
            )
        return self.converter.parse_uri(uri)


converter = Converter()


class ParseResult(BaseModel):
    """A container of results from parsing an SBML document."""

    template_model: TemplateModel


def template_model_from_sbml_file_path(
        file_path,
        *,
        model_id: Optional[str] = None,
        reporter_ids: Optional[Iterable[str]] = None,
) -> ParseResult:
    """Extract a MIRA template model from a file containing SBML XML."""
    with open(file_path, 'rb') as fh:
        return template_model_from_sbml_file(
            fh, model_id=model_id, reporter_ids=reporter_ids
        )


def template_model_from_sbml_file(
    file,
    *,
    model_id: Optional[str] = None,
    reporter_ids: Optional[Iterable[str]] = None,
) -> ParseResult:
    """Extract a MIRA template model from a file object containing SBML XML."""
    return template_model_from_sbml_string(
        file.read().decode("utf-8"), model_id=model_id, reporter_ids=reporter_ids
    )


def template_model_from_sbml_string(
    s: str,
    *,
    model_id: Optional[str] = None,
    reporter_ids: Optional[Iterable[str]] = None,
) -> ParseResult:
    """Extract a MIRA template model from a string representing SBML XML."""
    sbml_document = SBMLReader().readSBMLFromString(s)
    return template_model_from_sbml_document(
        sbml_document, model_id=model_id, reporter_ids=reporter_ids
    )


def template_model_from_sbml_document(
    sbml_document: SBMLDocument,
    *,
    model_id: Optional[str] = None,
    reporter_ids: Optional[Iterable[str]] = None,
) -> ParseResult:
    """Traverse an SBML document generated by libSBML and extract a MIRA Template model."""
    # see docs on models:
    # https://sbml.org/software/libsbml/5.18.0/docs/formatted/python-api/classlibsbml_1_1_s_b_m_l_document.html
    return template_model_from_sbml_model(
        sbml_document.model,
        model_id=model_id,
        reporter_ids=reporter_ids,
    )


def template_model_from_sbml_model(
    sbml_model,
    *,
    model_id: Optional[str] = None,
    reporter_ids: Optional[Iterable[str]] = None,
) -> ParseResult:
    """Traverse an SBML document generated by libSBML and extract a MIRA Template model."""
    reporter_ids = set(reporter_ids or [])
    concepts = _extract_concepts(sbml_model, model_id=model_id)

    def _lookup_concepts_filtered(species_ids) -> List[Concept]:
        return [
            concepts[species_id] for species_id in species_ids if species_id not in reporter_ids
        ]

    # Iterate thorugh all reactions and piecewise convert to templates
    templates: List[Template] = []
    # see docs on reactions
    # https://sbml.org/software/libsbml/5.18.0/docs/formatted/python-api/classlibsbml_1_1_reaction.html
    all_species = {species.id for species in sbml_model.species}
    all_parameters = {parameter.id: parameter.value
                      for parameter in sbml_model.parameters}
    parameter_symbols = {parameter.id: sympy.Symbol(parameter.id)
                         for parameter in sbml_model.parameters}
    compartment_symbols = {compartment.id: sympy.Symbol(compartment.id)
                           for compartment in sbml_model.compartments}
    # Add compartment volumes as parameters
    for compartment in sbml_model.compartments:
        all_parameters[compartment.id] = compartment.volume
    if 'lambda' in all_parameters:
        all_parameters['XXlambdaXX'] = all_parameters.pop('lambda')
    if 'lambda' in parameter_symbols:
        parameter_symbols['XXlambdaXX'] = sympy.Symbol('XXlambdaXX')

    # Handle custom function definitions in the model
    function_lambdas = {}
    for fun_def in sbml_model.function_definitions:
        args = [fun_def.getArgument(i).getName()
                for i in range(fun_def.getNumArguments())]
        arg_symbols = {arg: sympy.Symbol(arg) for arg in args}
        signature = tuple(arg_symbols.values())
        formula_str = get_formula_str(fun_def.getBody())
        if isinstance(formula_str, float) and math.isnan(formula_str):
            continue
        formula = sympy.parse_expr(formula_str, local_dict=arg_symbols)
        lmbd = sympy.Lambda(signature, formula)
        function_lambdas[fun_def.id] = lmbd

    all_locals = {k: v for k, v in (list(parameter_symbols.items()) +
                                    list(compartment_symbols.items()) +
                                    list(function_lambdas.items()))}

    # Handle custom assignment rules in the model
    assignment_rules = {}
    for rule in sbml_model.rules:
        assignment_rules[rule.id] = sympy.parse_expr(rule.formula,
                                                     local_dict=all_locals)

    for reaction in sbml_model.reactions:
        modifier_species = [species.species for species in reaction.modifiers]
        reactant_species = [species.species for species in reaction.reactants]
        product_species = [species.species for species in reaction.products]

        rate_law = reaction.getKineticLaw()

        def clean_formula(f):
            return f.replace('lambda', 'XXlambdaXX')

        rate_expr = sympy.parse_expr(clean_formula(rate_law.formula),
                                     local_dict=all_locals)
        # At this point we need to make sure we substitute the assignments
        rate_expr = rate_expr.subs(assignment_rules)

        rate_law_variables = variables_from_sympy_expr(rate_expr)

        # Implicit modifiers appear in the rate law but are not reactants and
        # aren't listed explicitly as modifiers. They have to be proper species
        # though (since the rate law also contains parameters).
        implicit_modifiers = ((set(rate_law_variables) & all_species)
                              - (set(reactant_species) | set(modifier_species)))
        # We extend modifiers with implicit ones
        modifier_species += sorted(implicit_modifiers)

        modifiers = _lookup_concepts_filtered(modifier_species)
        reactants = _lookup_concepts_filtered(reactant_species)
        products = _lookup_concepts_filtered(product_species)

        # check if reaction is reversible (i.e., reversible=False in the attributes),
        # then add a backwards conversion.
        if len(reactants) == 1 and len(products) == 1:
            if reactants[0].name and reactants[0] == products[0]:
                logger.debug(f"[{model_id} reaction:{reaction.id}]")
                logger.debug(f"Same reactant and product: {reactants[0]}")
                logger.debug(f"Modifiers: {modifiers}")
                continue
            if len(modifiers) == 0:
                templates.append(
                    NaturalConversion(
                        subject=reactants[0],
                        outcome=products[0],
                        rate_law=rate_expr,
                    )
                )
            elif len(modifiers) == 1:
                templates.append(
                    ControlledConversion(
                        subject=reactants[0],
                        outcome=products[0],
                        controller=modifiers[0],
                        rate_law=rate_expr,
                    )
                )
            else:
                # TODO reconsider adding different template that groups multiple controllers
                """
                could be the case that there's a linear combination of things that are independent
                - this could mean you could create multiple conversions

                but, they can be dependent too, then harder to break up
                """
                templates.append(
                    GroupedControlledConversion(
                        subject=reactants[0],
                        outcome=products[0],
                        controllers=modifiers,
                        rate_law=rate_expr,
                    )
                )
        elif not reactants and not products:
            logger.debug(f"[{model_id} reaction:{reaction.id}] missing reactants and products")
            continue
        elif products and not reactants:
            if len(products) == 1:
                templates.append(
                    NaturalProduction(
                        outcome=products[0],
                        rate_law=rate_expr,
                    )
                )
            else:
                logger.debug("can not yet handle multiple outcome natural production")
                continue
        elif reactants and not products:
            if len(reactants) == 1:
                templates.append(
                    NaturalDegradation(
                        subject=reactants[0],
                        rate_law=rate_expr,
                    )
                )
            else:
                logger.debug("can not yet handle multiple outcome natural degradation")
                continue
        else:
            logger.debug(
                f"[{model_id} reaction:{reaction.id}] skipping reaction with multiple inputs/outputs"
            )
            for i, inp in enumerate(reactants):
                logger.debug(f"reactant {i}: {inp!r}")
            for i, inp in enumerate(products):
                logger.debug(f"products {i}: {inp!r}")
            logger.debug("")
            continue

        # Later - mathematical modeling can introduce more complicated dependencies
        # that don't show up at the wiring level

    template_model = TemplateModel(templates=templates,
                                   parameters=all_parameters)
    return ParseResult(template_model=template_model)


def get_formula_str(ast_node):
    if not ast_node.getName():
        op = ast_node.getOperatorName()
        if op:
            if op == 'times':
                op_str = '*'
            elif op == 'plus':
                op_str = '+'
            elif op == 'divide':
                op_str = '/'
            elif op == 'minus':
                op_str = '-'
            else:
                print('Unknown op: %s' % op)
                assert False
            return '(%s %s %s)' % (get_formula_str(ast_node.getChild(0)),
                                   op_str,
                                   get_formula_str(ast_node.getChild(1)))
        val = ast_node.getValue()
        if val is not None:
            return val
    else:
        return ast_node.getName()


def variables_from_sympy_expr(expr):
    """Recursively find variables appearing in a sympy expression."""
    variables = set()
    if isinstance(expr, sympy.Symbol):
        variables.add(expr.name)
    else:
        assert isinstance(expr, sympy.Expr)
        for arg in expr.args:
            variables |= variables_from_sympy_expr(arg)
    return variables


def variables_from_ast(ast_node):
    """Recursively find variables appearing in a libSbml math formula.

    Note: currently unused but not removed for now since it may become
    necessary again.
    """
    variables_in_ast = set()
    # We check for any children first
    for child_id in range(ast_node.getNumChildren()):
        child = ast_node.getChild(child_id)
        # If the child has further children, we recursively add its variables
        if child.getNumChildren():
            variables_in_ast |= variables_from_ast(child)
        # Otherwise we just add the "leaf" child variable
        else:
            variables_in_ast.add(child.getName())
    # Now we add the node itself. Note that sometimes names are None which
    # we can ignore.
    name = ast_node.getName()
    if name:
        variables_in_ast.add(name)
    return variables_in_ast


def _extract_concepts(sbml_model, *, model_id: Optional[str] = None) -> Mapping[str, Concept]:
    """Extract concepts from an SBML model."""
    concepts = {}
    # see https://sbml.org/software/libsbml/5.18.0/docs/formatted/python-api/classlibsbml_1_1_species.html
    for species in sbml_model.getListOfSpecies():
        species_id = species.getId()
        species_name = species.getName()

        # The following traverses the annotations tag, which allows for
        # embedding arbitrary XML content. Typically, this is RDF.
        annotation_string = species.getAnnotationString()
        if not annotation_string:
            logger.debug(f"[{model_id} species:{species_id}] had no annotations")
            concepts[species_id] = Concept(name=species_name, identifiers={}, context={})
            continue

        annotation_tree = etree.fromstring(annotation_string)
        rdf_properties = [
            converter.parse_uri(desc.attrib[RESOURCE_KEY])
            for desc in annotation_tree.findall(PROPERTIES_XPATH, namespaces=PREFIX_MAP)
        ]
        # First we check identifiers with a specific relation representing
        # equivalence
        identifiers = dict(
            converter.parse_uri(element.attrib[RESOURCE_KEY])
            for element in annotation_tree.findall(IDENTIFIERS_XPATH, namespaces=PREFIX_MAP)
        )
        # As a fallback, we also check if identifiers are available with
        # a less specific relation
        if not identifiers:
            identifiers = dict(
                converter.parse_uri(element.attrib[RESOURCE_KEY])
                for element in annotation_tree.findall(IDENTIFIERS_VERSION_XPATH,
                                                       namespaces=PREFIX_MAP)
            )
        if model_id:
            identifiers["biomodels.species"] = f"{model_id}:{species_id}"
        concepts[species_id] = Concept(
            name=species_name or species_id,
            identifiers=identifiers,
            # TODO how to handle multiple properties? can we extend context to allow lists?
            context={"property": ":".join(rdf_properties[0])} if rdf_properties else {},
        )
    return concepts
