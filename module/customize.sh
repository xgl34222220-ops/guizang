#!/system/bin/sh
# Deliberately prevent installation of the unvalidated source tree.
# Magisk/KernelSU/APatch source this file with abort() defined. If a manager or a
# manual run does not provide it, still fail closed instead of continuing with
# "abort: not found" and a half-installed module.
if ! command -v abort >/dev/null 2>&1; then
  abort() {
    printf '! %s\n' "$1" >&2
    exit 1
  }
fi
abort "Guizang is a host-tested prototype, not an installable release."
# Unreachable with any abort() that honours its contract; fail closed regardless.
exit 1
