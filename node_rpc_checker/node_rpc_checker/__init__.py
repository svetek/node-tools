"""Specification-driven NEAR and EVM RPC readiness service."""

from importlib.resources import files

__version__ = files(__package__).joinpath("VERSION").read_text(encoding="utf-8").strip()
