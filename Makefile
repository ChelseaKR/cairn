# The development gate, in one place, so that "what CI runs" and "what a
# contributor runs" cannot be two different lists that drift apart.
#
# That sentence used to end "CI's `core` job calls these targets rather than
# repeating their commands", and it was not true. The job repeated a subset:
# `ruff check .` and a bare `unittest discover`, with no `mypy`, no
# `uv lock --check`, and no `coverage report` -- so the type check and the
# coverage floor were things a contributor ran and CI could not fail on, which
# is the drift the sentence claimed was impossible. The job runs all four now.
#
# It still spells the commands out rather than invoking these targets, because
# every target here goes through `uv run --locked` and therefore one pinned
# interpreter, while `core` is matrixed across supported Python versions and
# must use each one. tests/test_gate_parity.py holds the two lists equal with
# exactly that difference (`$(UVRUN)`) allowed and nothing else, so the claim
# above is now checked rather than asserted.
#
# `verify` is deliberately the offline half of the story and nothing more:
# lint, types, and the test suite, with no network and no auditor. The merge
# gate proper is ./plumbline-gate.sh, which grades a committed evidence bundle
# with an external auditor pinned to an exact commit, and which this file does
# not wrap. Wrapping it would invite `make verify` to be read as "the gate
# passed" when the gate is a separate, fail-closed job that must resolve a
# harness over the network. See "The merge gate" in README.md.
#
# Every invocation is `uv run --locked`, never a bare `uv run`. A bare `uv run`
# syncs implicitly: when uv.lock no longer agrees with pyproject.toml it
# rewrites the lockfile in place and carries on, so the gate would pass against
# a resolution nobody committed. `--locked` makes that an error instead.
UVRUN := uv run --locked --extra dev

.PHONY: install lock lock-check lint typecheck test verify demo clean

install:
	uv sync --locked --extra dev

# The only target allowed to rewrite uv.lock. Run it after changing a
# dependency, and commit the reviewable diff it produces.
lock:
	uv lock

# Fails when uv.lock no longer agrees with pyproject.toml. First in `verify`,
# because every later target would otherwise be the thing that repaired the
# lockfile it was supposed to be checked against.
lock-check:
	uv lock --check

lint:
	$(UVRUN) ruff check .

typecheck:
	$(UVRUN) mypy

test:
	$(UVRUN) coverage run -m unittest discover -s tests
	$(UVRUN) coverage report

# The demo path, run the way the README claims it can be run: no install, no
# virtual environment, no third-party package. If this stops working, the
# first page of the README has stopped being true.
demo:
	python3 -m cairn index
	python3 -m cairn ask "How much is the monthly grocery allowance for one person?"

verify: lock-check lint typecheck test
	@echo "verify: ok"

clean:
	rm -rf .coverage .ruff_cache .mypy_cache .pytest_cache
