"""EloPhanto core — Agent brain and foundation systems."""

from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("elophanto")
except Exception:
    __version__ = "dev"
