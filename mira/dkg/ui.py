import random

import flask
from flask import Blueprint, Response, render_template, request
from gilda.grounder import ScoredMatch

from .proxies import grounder

__all__ = ["ui_blueprint"]

ui_blueprint = Blueprint("ui", __name__)


@ui_blueprint.route("/", methods=["GET"])
def home():
    """Render the home page."""
    key = random.choice(list(grounder.entries))
    return render_template(
        "home.html",
        number_terms=len(grounder.entries),
        example_key=key,
        example_term=grounder.entries[key][0].to_json(),
    )