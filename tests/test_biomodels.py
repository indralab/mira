import os
import glob
import unittest

import tqdm
import pystow

from mira.sources.sbml import template_model_from_sbml_file


@unittest.skipIf(os.environ.get('GITHUB_ACTIONS') is not None,
                 reason="Meant to be run locally")
def test_process_biomodels():
    base_folder = pystow.join('mira', 'biomodels', 'models')
    fnames = glob.glob(os.path.join(base_folder.as_posix(),
                                    'BIOMD*/BIOMD*.xml'))
    for fname in tqdm.tqdm(fnames):
        tm = template_model_from_sbml_file(fname)
        assert tm.templates

