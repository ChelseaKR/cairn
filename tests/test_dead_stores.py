"""A container built up and never read.

Found as #67: ``cairn/tabular.py``'s ``parse_count_query`` appended to a
``bindings`` list on every matching column and never looked at it again. The
list was not merely dead — the function's docstring described an *ambiguity
rule over those bindings* that the code did not implement, so a reader
checking the behaviour against the prose would have concluded the check was
there. A dead store next to prose describing what it is for is worse than a
dead store, because it makes the prose look confirmed.

**Ruff cannot see this one.** ``F841`` is "local variable assigned but never
used", and ``bindings.append(...)`` reads ``bindings`` — the name is loaded,
so the rule is satisfied. Every use being a mutation is exactly the shape
that slips past it, and it is the shape a "collect it now, decide with it
later" edit leaves behind when the second half never lands or is removed.

So the rule here is narrower and complementary: a local name whose *only*
reads, anywhere in its function including closures, are as the receiver of a
mutating method call. The container is filled and nothing ever asks it
anything.

Two deliberate exemptions, both to keep this from crying wolf:

- names starting with ``_``, which are conventionally deliberate discards;
- a name never loaded at all, which is plain ``F841`` and ruff's job, not
  this file's.

One shape this cannot distinguish and would call wrongly is aliasing::

    rows = self._rows      # the alias IS the object
    rows.append(value)     # so this mutation is a real effect

Nothing in this repository does that today, which is why the check is worth
having here; if that pattern ever arrives, this test is where the exemption
gets written down with a reason next to it, rather than the check being
deleted.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Methods that mutate the receiver in place and return nothing worth keeping.
# `pop` is deliberately absent: it returns a value, so a `pop` is a read.
MUTATORS = frozenset(
    {
        "append",
        "appendleft",
        "add",
        "extend",
        "insert",
        "update",
        "discard",
        "remove",
        "sort",
        "clear",
        "setdefault",
    }
)

# A nested function or class is its own scope. Its assignments are not the
# enclosing function's locals, and counting them here is what made an earlier
# version of this check report `server_version` on a handler class.
NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def first_party_sources() -> list[Path]:
    """Everything this repository is responsible for.

    `.venv` and `.plumbline-cache` are somebody else's code, and third-party
    code does use the alias shape this check cannot read.
    """
    paths = sorted(ROOT.glob("*.py"))
    for directory in ("cairn", "tests"):
        paths += sorted((ROOT / directory).rglob("*.py"))
    return paths


def _own_scope_nodes(func: ast.AST) -> list[ast.AST]:
    """Nodes belonging to this function's own scope, nested scopes excluded."""
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(getattr(func, "body", []))
    while stack:
        node = stack.pop()
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, NESTED):
                continue
            stack.append(child)
    return nodes


def write_only_locals(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, int]]:
    """`(name, line)` for every local this function fills and never reads."""
    stored: dict[str, int] = {}
    for node in _own_scope_nodes(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stored.setdefault(node.id, node.lineno)
    if not stored:
        return []

    # Reads are collected from the whole subtree, closures included: a nested
    # function reading an enclosing local is a real read.
    reads: dict[str, list[ast.Name]] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            reads.setdefault(node.id, []).append(node)

    mutation_receivers = {
        id(node.func.value)
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in MUTATORS
        and isinstance(node.func.value, ast.Name)
    }

    found = []
    for name, line in sorted(stored.items()):
        if name.startswith("_"):
            continue
        occurrences = reads.get(name, [])
        if not occurrences:
            continue  # ruff's F841 already owns this one
        if all(id(node) in mutation_receivers for node in occurrences):
            found.append((name, line))
    return found


def scan(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for name, line in write_only_locals(node):
                findings.append(
                    f"{path.relative_to(ROOT)}:{line}: {node.name}() builds "
                    f"{name!r} and never reads it"
                )
    return findings


class TestNothingIsBuiltAndNeverRead(unittest.TestCase):
    def test_no_first_party_function_fills_a_container_it_never_reads(self):
        findings: list[str] = []
        for path in first_party_sources():
            findings += scan(path)
        self.assertEqual(
            findings,
            [],
            "a local is appended to and never read. Either the code that was "
            "going to read it is missing — check whether a docstring nearby "
            "promises a rule that is not there, which is what #67 turned out "
            "to be — or the collection is a leftover and goes, along with any "
            "prose describing it.",
        )

    def test_the_check_reports_the_shape_it_exists_for(self):
        """The guard's own guard.

        A checker that reports nothing is indistinguishable from a checker
        that cannot report. This is #67's code, reduced: a list appended to
        inside a loop and never consulted.
        """
        source = (
            "def f(rows):\n"
            "    bindings = []\n"
            "    keep = []\n"
            "    for row in rows:\n"
            "        bindings.append(row)\n"
            "        keep.append(row)\n"
            "    return keep\n"
        )
        func = ast.parse(source).body[0]
        self.assertEqual(write_only_locals(func), [("bindings", 2)])

    def test_a_container_that_is_read_is_not_reported(self):
        source = (
            "def f(rows):\n"
            "    out = []\n"
            "    for row in rows:\n"
            "        out.append(row)\n"
            "    return len(out)\n"
        )
        self.assertEqual(write_only_locals(ast.parse(source).body[0]), [])

    def test_a_closure_reading_the_local_is_a_read(self):
        source = (
            "def f(rows):\n"
            "    seen = []\n"
            "    for row in rows:\n"
            "        seen.append(row)\n"
            "    def report():\n"
            "        return seen\n"
            "    return report\n"
        )
        self.assertEqual(write_only_locals(ast.parse(source).body[0]), [])

    def test_a_nested_class_attribute_is_not_the_enclosing_function_s_local(self):
        """`cairn/server.py`'s handler factory declares a class inside a
        function. `server_version = ...` in that class body is an attribute,
        not a write-only local, and an earlier version of this check said
        otherwise.
        """
        source = (
            "def build():\n"
            "    class H:\n"
            "        server_version = 'x'\n"
            "    return H\n"
        )
        self.assertEqual(write_only_locals(ast.parse(source).body[0]), [])

    def test_the_scan_actually_reaches_the_tree(self):
        """A file list that came back empty would make the check above pass
        by having nothing to check.
        """
        paths = first_party_sources()
        self.assertGreater(len(paths), 50, "the first-party file list is suspiciously short")
        names = {path.name for path in paths}
        self.assertIn("tabular.py", names)
        self.assertIn("server.py", names)
        self.assertIn("audit_guard.py", names)


if __name__ == "__main__":
    unittest.main()
