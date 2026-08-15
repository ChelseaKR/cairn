"""Configuration loading.

Cairn is config-driven: swapping the corpus, tuning behavior, or changing what
a refusal tells people to do is a change to ``cairn.toml``, never a code
change. Every key has a default so the file may be sparse or absent; the
defaults point at the bundled synthetic demo corpus so a clean checkout works
immediately.

Writing direction is deliberately *not* configurable. It is a property of a
language, not of a deployment, and it lives in one place
(:mod:`cairn.language`) so it cannot be set two ways.

See DESIGN.md ("Configuration") for the rationale behind each default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = "cairn.toml"

# Fictional demo contacts, one per interface language. A real deployment must
# replace all of them; the parenthetical says so in the output itself.
_DEMO_CONTACTS = {
    "en": (
        "the Harbor County Community Assistance office at 555-0142 "
        "(a fictional demo contact; operators must configure their own)"
    ),
    "es": (
        "la oficina de Asistencia Comunitaria del Condado de Harbor, al 555-0142 "
        "(contacto ficticio de demostración; los operadores deben configurar el suyo)"
    ),
    "ar": (
        "مكتب المساعدة المجتمعية في مقاطعة هاربر على الرقم 555-0142 "
        "(جهة اتصال تجريبية مُختلَقة؛ على المشغّلين ضبط جهة اتصال خاصة بهم)"
    ),
}


class ConfigError(ValueError):
    """The configuration file is unreadable or a value has the wrong shape."""


@dataclass(frozen=True)
class Config:
    corpus_path: str = "corpus/demo"
    index_path: str = ".cairn/index.json"
    threshold: float = 0.165
    max_passages: int = 1
    candidates: int = 8
    default_lang: str = "en"
    cross_language_fallback: bool = True
    contact: str = _DEMO_CONTACTS["en"]
    contact_by_language: dict[str, str] = field(
        default_factory=lambda: dict(_DEMO_CONTACTS)
    )

    def contact_for(self, lang: str) -> str:
        """The human channel a refusal in ``lang`` should point to. Falls back
        to the single ``contact`` string, which is what a deployment that
        serves one language only ever needs to set."""
        return self.contact_by_language.get(lang, self.contact)


def _get(section: dict, key: str, kind: type, default):
    if key not in section:
        return default
    value = section[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
        raise ConfigError(f"config key {key!r} must be {kind.__name__}, got {value!r}")
    return value


def _contacts(refusal: dict) -> dict[str, str]:
    """Per-language overrides, exactly as written in the file. A deployment
    that serves one language sets ``contact`` and never touches this."""
    table = refusal.get("contact_by_language", {})
    if not isinstance(table, dict):
        raise ConfigError("refusal.contact_by_language must be a table of language codes")
    for code, value in table.items():
        if not isinstance(value, str):
            raise ConfigError(f"refusal.contact_by_language.{code} must be a string")
    return dict(table)


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
    language = data.get("language", {})
    defaults = Config()
    contact = _get(refusal, "contact", str, defaults.contact)
    cfg = Config(
        corpus_path=_get(corpus, "path", str, defaults.corpus_path),
        index_path=_get(index, "path", str, defaults.index_path),
        threshold=_get(retrieval, "threshold", float, defaults.threshold),
        max_passages=_get(retrieval, "max_passages", int, defaults.max_passages),
        candidates=_get(retrieval, "candidates", int, defaults.candidates),
        default_lang=_get(language, "default", str, defaults.default_lang),
        cross_language_fallback=_get(
            language, "cross_language_fallback", bool, defaults.cross_language_fallback
        ),
        contact=contact,
        contact_by_language=_contacts(refusal),
    )
    if not 0.0 < cfg.threshold <= 1.0:
        raise ConfigError("retrieval.threshold must be in (0, 1]: scores are bounded cosine")
    if cfg.max_passages < 1 or cfg.candidates < 1:
        raise ConfigError("retrieval.max_passages and retrieval.candidates must be >= 1")
    return cfg
