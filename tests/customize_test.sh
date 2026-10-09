#!/bin/sh
# Behavioural test: module/customize.sh must refuse installation both when the
# root manager provides abort() and when it does not.
set -eu
cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

# Case 1: no abort() defined -> fallback prints to stderr and exits non-zero.
status=0
sh module/customize.sh >"$tmp/out1" 2>"$tmp/err1" || status=$?
[ "$status" -ne 0 ] || { echo 'FAIL: customize.sh exited 0 without abort()' >&2; exit 1; }
grep -q 'not an installable release' "$tmp/err1" || { echo 'FAIL: fallback message missing' >&2; exit 1; }
echo 'ok   fallback abort refuses installation'

# Case 2: manager-style abort() (sourced, like Magisk/KernelSU/APatch).
cat >"$tmp/harness.sh" <<'H'
abort() { printf 'MANAGER_ABORT %s\n' "$1"; exit 1; }
. ./module/customize.sh
echo 'REACHED_AFTER_CUSTOMIZE'
H
status=0
sh "$tmp/harness.sh" >"$tmp/out2" 2>&1 || status=$?
[ "$status" -ne 0 ] || { echo 'FAIL: sourced customize.sh did not fail' >&2; exit 1; }
grep -q '^MANAGER_ABORT ' "$tmp/out2" || { echo 'FAIL: manager abort() not used' >&2; exit 1; }
if grep -q REACHED_AFTER_CUSTOMIZE "$tmp/out2"; then
  echo 'FAIL: installation continued after customize.sh' >&2
  exit 1
fi
echo 'ok   manager abort() is honoured'

# Case 3: a manager abort() that forgets to exit must still not continue.
cat >"$tmp/harness3.sh" <<'H'
abort() { printf 'SOFT_ABORT %s\n' "$1"; }
. ./module/customize.sh
echo 'REACHED_AFTER_CUSTOMIZE'
H
status=0
sh "$tmp/harness3.sh" >"$tmp/out3" 2>&1 || status=$?
[ "$status" -ne 0 ] || { echo 'FAIL: non-exiting abort() let install continue' >&2; exit 1; }
if grep -q REACHED_AFTER_CUSTOMIZE "$tmp/out3"; then
  echo 'FAIL: installation continued after soft abort' >&2
  exit 1
fi
echo 'ok   non-exiting abort() still fails closed'
echo 'customize.sh tests passed.'
