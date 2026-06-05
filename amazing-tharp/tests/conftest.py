"""Pytest configuration: ensure a SECRET_KEY is present before importing auth."""

import os
import sys

# Provide a deterministic key so auth.py imports cleanly and tokens can be created.
os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")

# Make the application modules importable (tests/ lives one level below repo root).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
