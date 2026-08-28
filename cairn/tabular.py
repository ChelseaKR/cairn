"""Structured corpus tables, and the deterministic tools that answer from them.

A corpus directory may carry a ``tables/`` subdirectory of CSV files whose
first lines are ``# key: value`` comments — the front-matter grammar, written
as comments so a spreadsheet round-trip survives it:

    # id: harbor-monthly-help-en
    # title: Harbor County Monthly Assistance Amounts
    # lang: en
    # synthetic: true
    program,monthly_benefit_usd,apply_online
    Fresh Start Grocery Allowance,212,yes

Tables are **corpus**, held to the same rules as documents: declared language,
synthetic marking, ids that can be cited (`<doc-id>` grammar, unique across
tables *and* documents), and inclusion in the corpus fingerprint so an edited
CSV is a stale index exactly like an edited paragraph.

What a question may do with them is deliberately narrow. One tool exists —
**count rows matching a numeric filter** ("how many programs pay more than
$100 a month") — and it fires only when every part binds without guessing:

- an explicit counting phrase (per language);
- exactly one column whose name shares vocabulary with the question (two
  candidates bind equally → fall through, never a coin flip);
- a comparison phrase and the number it acts on;
- every value under the bound column parseable as a number (a cell this rule
  cannot read disables the column rather than silently dropping rows).

Anything else returns ``None`` and the question goes to passage retrieval
untouched. The misfire bar is absolute: **no question the system already
answers may take the table path instead**, so the parser is checked against
the full audit question set in tests, not spot-checked by hand.

Grounding survives because composition stays extractive. The computed count
is spoken in Cairn's own voice — the notice field, where cross-language
notices already live — and never enters :attr:`Answer.text`, which remains
byte-for-byte the quoted cells. Every matched row is cited individually as
``<table-id>#<row-number>``, so the claim "1 of 3" is recompute-checkable
from the sources list alone.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cairn.corpus import DOC_ID, CorpusError
from cairn.language import normalize_code
from cairn.text import tokenize

TABLES_DIRNAME = "tables"

REQUIRED_TABLE_KEYS = ("id", "title", "lang", "synthetic")


@dataclass(frozen=True)
class Table:
    """One loaded CSV table. Cells are strings exactly as the file held them;
    rendering quotes them verbatim."""

    table_id: str
    title: str
    lang: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _parse_table_header(lines: list[str], path: Path) -> tuple[dict[str, str], int]:
    """The leading ``# key: value`` block, and how many lines it consumed."""
    meta: dict[str, str] = {}
    consumed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            break
        body = stripped.lstrip("#").strip()
        if not body:
            consumed += 1
            continue
        key, sep, value = body.partition(":")
        if not sep or not key.strip():
            raise CorpusError(f"{path}: bad header line: {line!r}")
        meta[key.strip()] = value.strip()
        consumed += 1
    return meta, consumed


def load_table(path: Path) -> Table:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    meta, consumed = _parse_table_header(raw_lines, path)
    missing = [key for key in REQUIRED_TABLE_KEYS if not meta.get(key)]
    if missing:
        raise CorpusError(
            f"{path}: table header missing required key(s): {', '.join(missing)}"
        )
    table_id = meta["id"]
    if not DOC_ID.match(table_id):
        raise CorpusError(
            f"{path}: table id {table_id!r} cannot be written as a citation "
            f"(same grammar as document ids)"
        )
    reader = csv.reader(raw_lines[consumed:])
    rows_raw = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows_raw:
        raise CorpusError(f"{path}: no header row of column names")
    columns = tuple(cell.strip() for cell in rows_raw[0])
    if not columns or not all(columns):
        raise CorpusError(f"{path}: every column needs a name")
    width = len(columns)
    rows: list[tuple[str, ...]] = []
    for number, row in enumerate(rows_raw[1:], start=1):
        cells = tuple(cell.strip() for cell in row)
        if len(cells) != width:
            raise CorpusError(
                f"{path}: row {number} has {len(cells)} cells, the header has {width}"
            )
        rows.append(cells)
    return Table(
        table_id=table_id,
        title=meta["title"],
        lang=normalize_code(meta["lang"]),
        columns=columns,
        rows=tuple(rows),
    )


def load_tables(corpus_dir: str | Path) -> tuple[Table, ...]:
    root = Path(corpus_dir) / TABLES_DIRNAME
    if not root.is_dir():
        return ()
    tables: list[Table] = []
    seen: set[str] = set()
    for path in sorted(root.glob("*.csv")):
        table = load_table(path)
        if table.table_id in seen:
            raise CorpusError(
                f"{path}: duplicate id {table.table_id!r}; a citation to it "
                f"resolves to whichever table a reader guessed"
            )
        seen.add(table.table_id)
        tables.append(table)
    return tuple(tables)


def table_paths(corpus_dir: str | Path) -> list[Path]:
    """The CSVs the loader would read — the fingerprint's other half."""
    root = Path(corpus_dir) / TABLES_DIRNAME
    if not root.is_dir():
        return []
    return sorted(root.glob("*.csv"))


# --- the tool ----------------------------------------------------------------

# Counting phrases, per interface language. A trigger alone commits to
# nothing; every other part must also bind before the tool runs.
_COUNT_TRIGGERS = (
    r"\bhow many\b",
    r"\bnumber of\b",
    r"\bcu[áa]nt[oa]s\b",
    r"\bn[uú]mero de\b",
    "كم عدد",
)

# Comparison phrases mapping to Python operators, longest first so "at least"
# wins over a bare match of a shorter phrase inside it.
_COMPARATORS: tuple[tuple[str, str], ...] = (
    (r"\bat least\b|\bal menos\b|على الأقل", ">="),
    (r"\bat most\b|\bcomo m[aá]ximo\b|كحد أقصى", "<="),
    (r"\bles?s than\b|\bfewer than\b|\bunder\b|\bbelow\b|\bmenos de\b|أقل من", "<"),
    (r"\bmore than\b|\bgreater than\b|\bover\b|\babove\b|\bm[aá]s de\b|أكثر من", ">"),
)

_NUMBER = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)")


@dataclass(frozen=True)
class TableQuery:
    """A fully-bound tool call. There is no partial form: anything less is
    ``None`` from :func:`parse_count_query`."""

    table_id: str
    column: str          # column name as the file declares it
    comparator: str      # "<", ">", "<=", ">="
    value: float
    op: str = "count"


def _column_stems(column: str) -> set[str]:
    return {token for token in tokenize(column.replace("_", " "))}


def _parse_number(text: str, after: int) -> float | None:
    match = _NUMBER.search(text[after:])
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _is_measure_column(table: Table, index: int) -> bool:
    """A column every cell of which parses as a number: a quantity a filter
    can act on. The other kind — row labels like ``program`` — is named in
    questions constantly ("how many *programs*…") and must never count as an
    ambiguous second binding when a real measure also matched."""
    try:
        for row in table.rows:
            float(row[index].replace("$", "").replace(",", "").strip())
        return bool(table.rows)
    except ValueError:
        return False


def _earliest_comparator(text: str) -> tuple[str, int] | None:
    """The comparison phrase that starts earliest in ``text``, as its operator
    symbol and the offset just past the phrase — or ``None`` when the question
    names no comparison at all.

    Earliest rather than first-listed, because the number the filter acts on is
    read forward from the end of the phrase (:func:`_parse_number`): a phrase
    further along the sentence would take its number from past the one the
    reader meant. Two phrases starting at the same offset are settled by
    ``_COMPARATORS`` order, which is why the comparison is strict — the entry
    listed first, the longer one, keeps the binding.
    """
    found: tuple[str, int] | None = None
    position = -1
    for pattern, symbol in _COMPARATORS:
        match = re.search(pattern, text)
        if match and (position == -1 or match.start() < position):
            found = (symbol, match.end())
            position = match.start()
    return found


def parse_count_query(question: str, tables: tuple[Table, ...]) -> TableQuery | None:
    """Bind every part of a count query, or decline entirely.

    Declining is the common case and the safe one: a question whose words
    happen to include a counting phrase but that binds to no column, or to
    two equally, belongs to passage retrieval. Row-label columns are exempt
    from the ambiguity rule when a measure column also binds — naming the
    rows ("how many programs") is not naming a number to filter.
    """
    lowered = question.lower()
    if not any(re.search(pattern, lowered) for pattern in _COUNT_TRIGGERS):
        return None

    question_terms = {token for token in tokenize(question)}
    bindings: list[tuple[Table, int]] = []  # (table, column index)
    measures: list[tuple[Table, int]] = []
    for table in tables:
        for index, column in enumerate(table.columns):
            overlap = _column_stems(column) & question_terms
            if not overlap:
                continue
            bindings.append((table, index))
            if _is_measure_column(table, index):
                measures.append((table, index))
    # Only a measure column can carry a comparison; a label-only bind means
    # the question named its rows but no number to filter them by, and the
    # honest move is to let passage retrieval have it.
    if len(measures) != 1:
        return None
    table, column_index = measures[0]

    comparison = _earliest_comparator(lowered)
    if comparison is None:
        return None
    comparator, end = comparison
    value = _parse_number(lowered, end)
    if value is None:
        return None
    return TableQuery(
        table_id=table.table_id,
        column=table.columns[column_index],
        comparator=comparator,
        value=value,
    )


_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
}


def run_count(query: TableQuery, tables: tuple[Table, ...]) -> tuple[Table, list[int]] | None:
    """The matching rows, in file order — or ``None`` when the bound column
    holds something this arithmetic refuses to interpret."""
    table = next((t for t in tables if t.table_id == query.table_id), None)
    if table is None or query.column not in table.columns:
        return None
    column_index = table.columns.index(query.column)
    compare = _OPS[query.comparator]
    matched: list[int] = []
    for row_number, row in enumerate(table.rows, start=1):
        cell = row[column_index].replace("$", "").replace(",", "").strip()
        try:
            number = float(cell)
        except ValueError:
            # A cell the operation cannot read disables the whole column:
            # skipping just that row would make the count silently wrong.
            return None
        if compare(number, query.value):
            matched.append(row_number)
    return table, matched


def render_row(table: Table, row_number: int) -> str:
    """One row as Cairn quotes it: ``column: cell`` pairs, file order,
    cells byte-for-byte as the CSV holds them."""
    cells = table.rows[row_number - 1]
    return "; ".join(
        f"{name}: {value}" for name, value in zip(table.columns, cells, strict=True)
    )
