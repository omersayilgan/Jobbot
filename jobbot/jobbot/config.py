"""Loads config.yaml / companies.yaml and exposes them as plain dicts."""
from __future__ import annotations

import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str) -> dict:
    path = os.path.join(ROOT, name)
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config() -> dict:
    return _load("config.yaml")


def load_companies() -> dict:
    return _load("companies.yaml")


def resolve(path: str) -> str:
    """Resolve a config-relative path (e.g. '../cv.pdf') against the project root."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(ROOT, path))


def output_dir() -> str:
    d = os.path.join(ROOT, "output")
    os.makedirs(d, exist_ok=True)
    return d
