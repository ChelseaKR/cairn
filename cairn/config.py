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

from cairn.language import LANGUAGES

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
    "fr": (
        "le bureau d'Assistance Communautaire du comté de Harbor, au 555-0142 "
        "(contact fictif de démonstration ; les opérateurs doivent configurer le leur)"
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
    # Below this gap between the winning candidate and its runner-up,
    # explain mode flags the retrieval as a near-tie. Diagnostic only: it
    # never changes which candidate is accepted or composed, only whether
    # `--explain` warns about how close the ranking was. 0.02 is comfortably
    # smaller than the measured calibration gap (0.032-0.043) so it does not
    # fire on ordinary in-corpus answers, and comfortably larger than zero so
    # it catches the documented GoPass near-tie (0.008 apart) rather than
    # only exact ties.
    margin_warn: float = 0.02
    # Weight of the dense (hashed character-n-gram) channel in the fused
    # score. See cairn.toml's own comment on `retrieval.dense_weight` for
    # what it trades off; 0 is lexical-only and byte-identical to the
    # channel not existing at all.
    dense_weight: float = 0.0
    default_lang: str = "en"
    cross_language_fallback: bool = True
    contact: str = _DEMO_CONTACTS["en"]
    contact_by_language: dict[str, str] = field(
        default_factory=lambda: dict(_DEMO_CONTACTS)
    )

    def __post_init__(self) -> None:
        """Validate on construction, not only on load.

        These bounds used to live in :func:`load_config`, which meant they
        held for `cairn.toml` and for nothing else. This is a reference
        implementation an agency is invited to import, and
        ``Config(max_passages=0)`` — a plausible reading of "no limit" —
        produced a **grounded answer with no sources and no text**: composition
        sliced the accepted passages to nothing while the trace still said
        passages had been accepted, so `kind` stayed "grounded" and
        `to_payload()["grounded"]` stayed true. That is the one thing this
        project says cannot happen, arriving through the constructor rather
        than through the corpus. A negative value was quieter and no better:
        `accepted[:-1]` silently drops the *last* accepted passage rather than
        meaning "all of them".

        The invariant is a property of the configuration, so it is enforced
        where the configuration is made.
        """
        if not 0.0 < self.threshold <= 1.0:
            raise ConfigError(
                "retrieval.threshold must be in (0, 1]: scores are bounded cosine"
            )
        if self.max_passages < 1:
            raise ConfigError(
                "retrieval.max_passages must be >= 1: composing zero passages "
                "would emit an answer with no source behind it, which is the "
                "one outcome this system does not have"
            )
        if self.candidates < 1:
            raise ConfigError("retrieval.candidates must be >= 1")
        if self.margin_warn < 0.0:
            raise ConfigError(
                "retrieval.margin_warn must be >= 0: it is a score gap, and a "
                "negative gap is not a gap"
            )
        if not 0.0 <= self.dense_weight <= 0.5:
            raise ConfigError(
                "retrieval.dense_weight must be in [0, 0.5]: the dense channel "
                "re-ranks lexical candidates and may never outvote them — a "
                "hybrid score that is mostly subword similarity would answer "
                "from passages the question barely touches"
            )
        # `language.default` is the language Cairn *speaks* when it cannot
        # tell what was asked — the refusal, the cross-language notice, the
        # interface chrome. It was unvalidated, and the same "bounds at the
        # edge" shape as max_passages: the server checks the selector value
        # against its own list and the engine checks an explicitly requested
        # language against the corpus, so both edges were guarded and the
        # value that skips both edges was not. `Config(default_lang="de")`
        # produced a grounded answer labelled `lang: "de"` carrying an English
        # cross-language notice, because `messages.catalogue_for` falls back
        # to English for a code it has no catalogue for; with "he" it also
        # came out `dir="rtl"` with an English body. An operator serving
        # German would write exactly that line. (French was this example
        # too, once — `LANGUAGES` has since grown a real `fr` catalogue, so
        # the bug it demonstrated stopped reproducing for that code.)
        if self.default_lang not in LANGUAGES:
            raise ConfigError(
                f"language.default must be a language Cairn has system strings "
                f"for ({', '.join(sorted(LANGUAGES))}), got {self.default_lang!r}. "
                f"A corpus may be in any language; the language Cairn answers "
                f"and refuses in may not be one it cannot write a refusal in."
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


def _contacts(refusal: dict, defaults: dict[str, str]) -> dict[str, str]:
    """Per-language overrides, resolved the way every other key here resolves.

    A key absent from the file means "use the built-in default", and this one
    did not honour that. Passing ``{}`` for an absent table overrode the
    dataclass's own per-language defaults, so a `cairn.toml` that set only
    ``[corpus] path`` served an Arabic speaker a refusal that ended in the
    English contact line — while *no config file at all* served them the
    Arabic one. The file was less safe than its absence, for a key it never
    mentioned.

    The middle case is the one that has to stay safe. An operator who sets
    ``contact`` and no table has stated one channel for every language, and
    must not have Cairn's fictional demo contacts filled in around it: an
    invented Spanish phone number in a real deployment is worse than an
    English one that is at least real.
    """
    if "contact_by_language" not in refusal:
        # An operator's own single contact serves every language; otherwise
        # the built-in demo set, which is what `Config()` gives.
        return {} if "contact" in refusal else dict(defaults)
    table = refusal["contact_by_language"]
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
    # Bounds are checked by Config itself (see __post_init__), so a file and a
    # caller cannot be held to two different sets of rules.
    return Config(
        corpus_path=_get(corpus, "path", str, defaults.corpus_path),
        index_path=_get(index, "path", str, defaults.index_path),
        threshold=_get(retrieval, "threshold", float, defaults.threshold),
        max_passages=_get(retrieval, "max_passages", int, defaults.max_passages),
        candidates=_get(retrieval, "candidates", int, defaults.candidates),
        margin_warn=_get(retrieval, "margin_warn", float, defaults.margin_warn),
        dense_weight=_get(retrieval, "dense_weight", float, defaults.dense_weight),
        default_lang=_get(language, "default", str, defaults.default_lang),
        cross_language_fallback=_get(
            language, "cross_language_fallback", bool, defaults.cross_language_fallback
        ),
        contact=contact,
        contact_by_language=_contacts(refusal, defaults.contact_by_language),
    )
