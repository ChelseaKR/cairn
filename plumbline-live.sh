#!/bin/sh
#
# Grade the running engine, not a recording of it.
#
#   ./plumbline-gate.sh     # the merge gate: the committed bundle, offline
#   ./plumbline-live.sh     # the same questions, asked over HTTP
#
# What this does, in order:
#   1. Finds the pinned harness that ./plumbline-gate.sh already resolved.
#   2. Starts `cairn serve` on the port plumbline/live.toml points at.
#   3. Runs `plumbline record` against it: the harness asks all 26 questions
#      over HTTP and seals what comes back into an evidence bundle.
#   4. Runs `plumbline audit` on that bundle, with the floors the offline
#      target uses.
#   5. Runs live_check.py, which compares the answers to the committed
#      evidence byte for byte and the served page to the audited snapshot.
#
# THIS IS NOT THE GATE, AND CANNOT BECOME ONE
#
# The gate is ./plumbline-gate.sh: offline, deterministic, byte-reproducible,
# and named by plumbline.pin. This script grades a process that has to be
# running, over a socket, and stamps the moment into the evidence. Those are
# not the same kind of claim and the second must never be allowed to stand in
# for the first.
#
# So this script deliberately CANNOT FETCH THE HARNESS. It reads the pinned
# commit and requires that a checkout already exists at it, and tells you to
# run the gate if one does not. Resolution has exactly one implementation in
# this repository — the runner vendored from Plumbline, unmodified — and a
# path that grades a running server must not also be the path that installs
# the thing doing the grading. It also means you cannot run this against a
# harness the gate has never verified.
#
# Exit codes:
#   0  the served answers match the graded ones, and the audit passed
#   1  they differ, or a suite failed
#   4  the check could not be made (no resolved harness, server never came up,
#      no config). Never reported as agreement.

set -eu

EXIT_ENVIRONMENT=4

PIN_FILE="${PLUMBLINE_PIN_FILE:-plumbline.pin}"
LIVE_CONFIG="${CAIRN_LIVE_CONFIG:-plumbline/live.toml}"
CACHE_ROOT="${PLUMBLINE_CACHE_DIR:-.plumbline-cache}"
PLUMBLINE_PYTHON="${PLUMBLINE_PYTHON:-python3}"
AUDIT_OUT="${CAIRN_LIVE_AUDITS:-.plumbline-live/audits}"

fail() {
    printf 'PLUMBLINE LIVE: %s\n' "$1" >&2
    printf 'PLUMBLINE LIVE: the served interface was NOT graded. A check that could not run is not a check that passed.\n' >&2
    exit "$EXIT_ENVIRONMENT"
}

# `plumbline audit` has no --summary-file (only `gate` does), so it is read
# here and handed to the comparison instead of passed through blindly.
summary_file=''
while [ $# -gt 0 ]; do
    case "$1" in
        --summary-file) [ $# -ge 2 ] || fail "--summary-file needs a path"
                        summary_file=$2; shift 2 ;;
        --summary-file=*) summary_file=${1#--summary-file=}; shift ;;
        *) fail "unknown argument '$1' (this runner takes --summary-file PATH)" ;;
    esac
done

[ -f "$PIN_FILE" ] || fail "no pin file at '$PIN_FILE'"
[ -f "$LIVE_CONFIG" ] || fail "no live target config at '$LIVE_CONFIG'"

pin_ref=$(sed -n 's/^[ 	]*ref[ 	]*=[ 	]*\([0-9a-f]*\).*/\1/p' "$PIN_FILE" | head -n 1)
[ -n "$pin_ref" ] || fail "'$PIN_FILE' does not name a commit in a 'ref =' line"

harness_src="$CACHE_ROOT/$pin_ref/src"
if [ ! -d "$harness_src" ]; then
    fail "the harness pinned at $pin_ref is not resolved in '$CACHE_ROOT'. Run ./plumbline-gate.sh first: that is the one thing in this repository that fetches it, deliberately, so that grading a live server can never be the act that installs its own auditor."
fi
resolved=$(git -C "$CACHE_ROOT/$pin_ref" rev-parse HEAD 2>/dev/null) \
    || fail "'$CACHE_ROOT/$pin_ref' is not a readable checkout"
[ "$resolved" = "$pin_ref" ] \
    || fail "the resolved harness is at $resolved but $PIN_FILE pins $pin_ref"

command -v "$PLUMBLINE_PYTHON" >/dev/null 2>&1 \
    || fail "'$PLUMBLINE_PYTHON' is not available"

# The endpoint is written once, in the live config. Reading the host and port
# back out of it is what stops the server from being started somewhere the
# recorder is not looking.
#
# Assigned in two steps rather than `eval "$(...)"` in one: a command
# substitution that fails still produces an empty string, and `eval ""`
# succeeds, so a one-liner would sail past a broken config with the variables
# unset. Capturing first makes the failure the script's own exit 4.
endpoint_vars=$("$PLUMBLINE_PYTHON" - "$LIVE_CONFIG" <<'PY'
import sys, tomllib
from urllib.parse import urlparse
with open(sys.argv[1], "rb") as f:
    endpoint = tomllib.load(f)["adapter"]["endpoint"]
parts = urlparse(endpoint)
if not parts.hostname or not parts.port:
    raise SystemExit(f"[adapter].endpoint has no host and port: {endpoint!r}")
print(f"LIVE_HOST={parts.hostname}")
print(f"LIVE_PORT={parts.port}")
PY
) || fail "'$LIVE_CONFIG' does not carry a usable [adapter].endpoint"
eval "$endpoint_vars"

printf 'PLUMBLINE LIVE: harness %s\n' "$pin_ref"
printf 'PLUMBLINE LIVE: serving cairn on %s:%s\n' "$LIVE_HOST" "$LIVE_PORT"

"$PLUMBLINE_PYTHON" -m cairn index >/dev/null

# Refuse a port something else already holds. Found the hard way: a forgotten
# server from an earlier run answered every question, and the recording was of
# a build nobody was testing. "Something was listening" is not "the thing I
# started was listening", and a live check that cannot tell them apart grades
# whatever happens to be there.
"$PLUMBLINE_PYTHON" - "$LIVE_HOST" "$LIVE_PORT" <<'PY' || fail "something is already listening on that address; this run would have recorded whatever it is"
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=0.5):
        sys.exit(1)
except OSError:
    sys.exit(0)
PY

server_pid=''
cleanup() {
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

"$PLUMBLINE_PYTHON" -m cairn serve --host "$LIVE_HOST" --port "$LIVE_PORT" --quiet &
server_pid=$!

# Wait for it, bounded. A server that never came up is exit 4, not a low score.
"$PLUMBLINE_PYTHON" - "$LIVE_HOST" "$LIVE_PORT" <<'PY' || fail "the server did not start listening"
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            sys.exit(0)
    except OSError:
        time.sleep(0.1)
sys.exit(1)
PY

kill -0 "$server_pid" 2>/dev/null || fail "the server exited while starting up"

export PYTHONPATH="$harness_src${PYTHONPATH:+:$PYTHONPATH}"

# --synthetic: the target is this repository's own demo over a synthetic
# corpus. Recording against something real, that flag comes off, and the
# manifest stops claiming the evidence is invented.
"$PLUMBLINE_PYTHON" -m plumbline record \
    --config "$LIVE_CONFIG" \
    --overwrite \
    --synthetic \
    --note "cairn serve on ${LIVE_HOST}:${LIVE_PORT}, driven by ./plumbline-live.sh"

"$PLUMBLINE_PYTHON" -m plumbline audit --config "$LIVE_CONFIG" --out "$AUDIT_OUT"

unset PYTHONPATH

if [ -n "$summary_file" ]; then
    "$PLUMBLINE_PYTHON" live_check.py --config "$LIVE_CONFIG" \
        --summary-file "$summary_file"
else
    "$PLUMBLINE_PYTHON" live_check.py --config "$LIVE_CONFIG"
fi
