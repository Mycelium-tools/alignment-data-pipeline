"""Shared utilities for the alignment data pipeline.

A minimum-Python check lives here because every entrypoint (`sdf_pipeline/run.py`,
`dad_pipeline/run.py`, and the `evals/` scripts) imports `shared` before any heavy
dependency. Running it at package-import time means a too-old interpreter gets one
clear sentence instead of a confusing failure deep inside numpy/pandas/anthropic.

The floor matches what the dependencies themselves require (numpy needs >=3.12),
so this never blocks a setup that would otherwise work — it only improves the
error message. Bump MIN_PYTHON if the dependencies' floor rises.
"""

import sys

MIN_PYTHON = (3, 12)

if sys.version_info < MIN_PYTHON:
    sys.exit(
        f"This pipeline needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, "
        f"but you are running {sys.version.split()[0]}.\n"
        "Recreate your virtual environment on a newer Python "
        "(see the Setup section of README.md)."
    )
