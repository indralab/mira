__all__ = ["Model", "Transition", "Variable", "Parameter"]

import logging

from mira.metamodel import (
    ControlledConversion, NaturalConversion, NaturalProduction, NaturalDegradation,
    GroupedControlledConversion,
)


logger = logging.getLogger(__name__)


class Transition:
    def __init__(self, key, consumed, produced, control, rate):
        self.key = key
        self.consumed = consumed
        self.produced = produced
        self.control = control
        self.rate = rate


class Variable:
    def __init__(self, key, data=None):
        self.key = key
        self.data = data


class Parameter:
    def __init__(self, key):
        self.key = key


def get_transition_key(concept_keys, action):
    return concept_keys + (action,)


def get_parameter_key(transition_key, action):
    return transition_key + (action,)


UNHANDLED_TYPES = set()


class Model:
    def __init__(self, template_model):
        self.template_model = template_model
        self.variables = {}
        self.parameters = {}
        self.transitions = {}
        self.make_model()

    def assemble_variable(self, concept):
        grounding_key = sorted(("identity", f"{k}:{v}")
                               for k, v in concept.identifiers.items()
                               if k != "biomodel.species")
        context_key = sorted(concept.context.items())
        key = [concept.name] + grounding_key + context_key
        key = tuple(key) if len(key) > 1 else key[0]
        if key in self.variables:
            return self.variables[key]

        data = {
            'name': concept.name,
            'identifiers': grounding_key,
            'context': context_key
        }
        var = Variable(key, data)
        self.variables[key] = var
        return var

    def make_model(self):
        for template in self.template_model.templates:
            if isinstance(template, (NaturalConversion, NaturalProduction, NaturalDegradation)):
                if isinstance(template, (NaturalConversion, NaturalDegradation)):
                    s = self.assemble_variable(template.subject)
                    consumed = (s,)
                else:
                    consumed = tuple()
                if isinstance(template, (NaturalConversion, NaturalProduction)):
                    o = self.assemble_variable(template.outcome)
                    produced = (o,)
                else:
                    produced = tuple()

                consumed_key = tuple(s.key for s in consumed) \
                    if len(consumed) != 1 else consumed[0].key
                produced_key = tuple(o.key for o in produced) \
                    if len(produced) != 1 else produced[0].key
                tkey = get_transition_key((consumed_key, produced_key),
                                          template.type)
                p = self.get_create_parameter(
                    Parameter(get_parameter_key(tkey, 'rate')))
                self.get_create_transition(Transition(
                    tkey,
                    consumed=consumed,
                    produced=produced,
                    control=tuple(),
                    rate=p,
                ))
            elif isinstance(template, (ControlledConversion, GroupedControlledConversion)):
                s = self.assemble_variable(template.subject)
                o = self.assemble_variable(template.outcome)

                if isinstance(template, ControlledConversion):
                    c = self.assemble_variable(template.controller)
                    control = (c,)
                    tkey = get_transition_key((s.key, o.key, c.key), template.type)
                else:
                    control = tuple(
                        self.assemble_variable(controller)
                        for controller in template.controllers
                    )
                    tkey = get_transition_key((s.key, o.key,
                                               tuple(c.key for c in control)),
                                              template.type)

                p = self.get_create_parameter(
                    Parameter(get_parameter_key(tkey, 'rate')))
                self.get_create_transition(Transition(
                    tkey,
                    consumed=(s,),
                    produced=(o,),
                    control=control,
                    rate=p,
                ))
            else:
                if template.__class__ not in UNHANDLED_TYPES:
                    logger.warning("unhandled template type: %s", template.__class__)
                    UNHANDLED_TYPES.add(template.__class__)

    def get_create_parameter(self, parameter):
        if parameter.key not in self.parameters:
            self.parameters[parameter.key] = parameter
        return self.parameters[parameter.key]

    def get_create_transition(self, transition):
        if transition.key not in self.transitions:
            self.transitions[transition.key] = transition
        return self.transitions[transition.key]
