#!/bin/sh
#
# The gauntlet gate: run the pinned evaluation suites against this
# repository's engine.
#
#   ./gauntlet-gate.sh
#
# What it does, in order:
#   1. Reads gauntlet.pin: repository, exact commit, suites, target.
#   2. Requires a checkout of the harness already existing at that commit —
#      $GAUNTLET_CHECKOUT, or a sibling `gauntlet` whose HEAD matches.
#   3. Runs `gauntlet run` over the suites against the callable target.
#
# THIS SCRIPT CANNOT INSTALL THE HARNESS THAT GRADES IT
#
# Resolution has one implementation per consumer in this repository's
# history: plumbline's is the runner vendored from Plumbline itself, and this
# one deliberately does not fetch at all. If no checkout exists at the pinned
# commit the gate exits 4 — "told you nothing" — rather than resolving
# something else and grading against whatever it got. A gate that installs
# its own judge after losing track of the commit is a green tick pointing at
# nothing.
#
# Exit codes:
#   0  every suite cleared its threshold
#   1  a gate failed (the merge-blocking case)
#   4  the check could not be made: no pin, no checkout at the pin, harness
#      could not run. Never reported as agreement.

set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
PIN="$ROOT/gauntlet.pin"
RESULTS="$ROOT/.cairn/gauntlet-results.json"

[ -f "$PIN" ] || { echo "GATE: FAIL - no $PIN" >&2; exit 4; }

REPO=$(sed -n 's/^repository = "\(.*\)"/\1/p' "$PIN")
COMMIT=$(sed -n 's/^commit = "\(.*\)"/\1/p' "$PIN")
SUITES=$(sed -n 's/^suites = "\(.*\)"/\1/p' "$PIN")
TARGET=$(sed -n 's/^target = "\(.*\)"/\1/p' "$PIN")

[ -n "$REPO" ] && [ -n "$COMMIT" ] && [ -n "$SUITES" ] && [ -n "$TARGET" ] || {
    echo "GATE: FAIL - gauntlet.pin is missing a required key" >&2; exit 4;
}

checkout_head() {
    git -C "$1" rev-parse HEAD 2>/dev/null
}

CHECKOUT="${GAUNTLET_CHECKOUT:-}"
if [ -z "$CHECKOUT" ]; then
    for candidate in "$ROOT/../gauntlet" "$ROOT/gauntlet-checkout"; do
        if [ -d "$candidate/.git" ] && [ "$(checkout_head "$candidate")" = "$COMMIT" ]; then
            CHECKOUT=$candidate
            break
        fi
    done
fi

if [ -z "$CHECKOUT" ]; then
    echo "GATE: COULD NOT RUN (exit 4)" >&2
    echo "  no checkout of $REPO at the pinned commit $COMMIT was found." >&2
    echo "  Set GAUNTLET_CHECKOUT to a checkout whose HEAD is that commit," >&2
    echo "  or clone: git clone https://github.com/$REPO and check out $COMMIT." >&2
    echo "  This gate does not fetch its own harness; that is deliberate." >&2
    exit 4
fi

if [ "$(checkout_head "$CHECKOUT")" != "$COMMIT" ]; then
    echo "GATE: FAIL (exit 4) - $CHECKOUT is not at the pinned commit" >&2
    echo "  found: $(checkout_head "$CHECKOUT"), pinned: $COMMIT" >&2
    exit 4
fi

mkdir -p "$(dirname "$RESULTS")"

PYTHONPATH="$ROOT:$CHECKOUT/src" \
uv run --project "$CHECKOUT" gauntlet run \
    --cases "$ROOT/$SUITES" \
    --callable "$TARGET" \
    --out "$RESULTS"

echo "GATE: PASS - suites in $SUITES cleared their thresholds"
