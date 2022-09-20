"""Tests for the triples generator."""

import unittest

from mira.examples.sir import sir
from mira.modeling.triples import TriplesGenerator


class TestTriplesGenerator(unittest.TestCase):
    """Test the triples generator."""

    def test_sir(self):
        """This test makes sure there are connections
        between the three grounded IDO terms in the SIR model.
        """
        generator = TriplesGenerator(sir)
        self.assertEqual(
            {
                (
                    "ido:0000511",
                    "ro:0002323",
                    "ido:00005",
                ),
                (
                    "ido:0000514",
                    "ro:0002323",
                    "ido:0000511",
                ),
            },
            set(generator.triples),
        )
