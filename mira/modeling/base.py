"""Base classes for model generators."""

from typing import List, Union

from pydantic import BaseModel, Field

from ..metamodel import TemplateModel

__all__ = ["Generator"]

class Generator:
    """A base class for generators."""

    def __init__(self, model: TemplateModel):
        self.model = model
