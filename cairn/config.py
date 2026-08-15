"""Configuration loading.

Cairn is config-driven: swapping the corpus or tuning behavior is a change to
``cairn.toml``, never a code change. Every key has a default so the file may
be sparse or absent; the defaults point at the bundled synthetic demo corpus
so a clean checkout works immediately.

See DESIGN.md ("Configuration") for the rationale behind each default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = "cairn.toml"


class ConfigError(ValueError):
    """The configuration file is unreadable or a value has the wrong shape."""


@dataclass(frozen=True)
class Config:
    corpus_path: str = "corpus/demo"
    index_path: str = ".cairn/index.json"
    threshold: float = 0.20
    max_passages: int = 2
    candidates: int = 8
    contact: str = (
        "the Harbor County Community Assistance office at 555-0142 "
        "(a fictional demo contact; operators must configure their own)"
    )


def _get(section: dict, key: str, kind: type, default):
    if key not in section:
        return default
    value = section[key]
    if kind is float and isinstance(value, int):
        value = float(value)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise ConfigError(f"config key {key!r} must be {kind.__name__}, got {value!r}")
    return value


def load_config(path: str | Path | None = None) -> Config:
    """Load ``cairn.toml``. An explicitly named file must exist; the default
    location is optional and silently falls back to built-in defaults."""
    explicit = path is not None
    cfg_path = Path(path or DEFAULT_CONFIG_PATH)
    if not cfg_path.is_file():
        if explicit:
            raise ConfigError(f"config file not found: {cfg_path}")
        return Config()
    try:
        with open(cfg_path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{cfg_path}: invalid TOML: {exc}") from exc

    corpus = data.get("corpus", {})
    index = data.get("index", {})
    retrieval = data.get("retrieval", {})
    refusal = data.get("refusal", {})
    defaults = Config()
    cfg = Config(
        corpus_path=_get(corpus, "path", str, defaults.corpus_path),
        index_path=_get(index, "path", str, defaults.index_path),
        threshold=_get(retrieval, "threshold", float, defaults.threshold),
        max_passages=_get(retrieval, "max_passages", int, defaults.max_passages),
        candidates=_get(retrieval, "candidates", int, defaults.candidates),
        contact=_get(refusal, "contact", str, defaults.contact),
    )
    if not 0.0 < cfg.threshold <= 1.0:
        raise ConfigError("retrieval.threshold must be in (0, 1]: scores are bounded cosine")
    if cfg.max_passages < 1 or cfg.candidates < 1:
        raise ConfigError("retrieval.max_passages and retrieval.candidates must be >= 1")
    return cfg
