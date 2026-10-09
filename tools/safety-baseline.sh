#!/bin/sh
# Static safety baseline for the module tree on main. Runs on any POSIX host;
# no device, root, network or extra dependencies (python3 is only used for JSON).
set -eu
cd "$(dirname "$0")/.."

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}
ok() {
  printf 'ok   %s\n' "$1"
}

# 1. Shell syntax for every module/tool/test script.
for file in module/*.sh tools/*.sh tests/*.sh; do
  [ -f "$file" ] || continue
  sh -n "$file" || fail "shell syntax: $file"
done
ok 'shell syntax'

# 2. shellcheck when available (CI installs it; local runs may skip).
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -s sh module/*.sh tools/*.sh tests/*.sh || fail 'shellcheck'
  ok 'shellcheck'
else
  printf 'skip shellcheck (not installed)\n'
fi

# 3. Never ship boot-blocking or policy-changing stages from this prototype.
for forbidden in module/post-fs-data.sh module/sepolicy.rule module/system.prop; do
  [ ! -e "$forbidden" ] || fail "forbidden file present: $forbidden"
done
ok 'no post-fs-data / sepolicy / system.prop'

# 4. Installation must stay blocked.
grep -q '^abort ' module/customize.sh || fail 'customize.sh no longer aborts'
ok 'customize.sh aborts installation'

# 5. module.prop must be well-formed for root managers.
prop=module/module.prop
for key in id name version versionCode author description; do
  grep -q "^$key=" "$prop" || fail "module.prop missing $key"
done
id=$(sed -n 's/^id=//p' "$prop")
printf '%s\n' "$id" | grep -Eq '^[a-zA-Z][a-zA-Z0-9._-]+$' || fail "module.prop id invalid: $id"
code=$(sed -n 's/^versionCode=//p' "$prop")
printf '%s\n' "$code" | grep -Eq '^[0-9]+$' || fail "module.prop versionCode not numeric: $code"
if grep -q "$(printf '\r')" "$prop"; then
  fail 'module.prop has CRLF line endings'
fi
ok 'module.prop fields'

# 6. Default configuration must stay inert.
python3 - <<'PY' || fail 'config/default.json is not safe-by-default'
import json
with open("config/default.json", encoding="utf-8") as fh:
    c = json.load(fh)
assert c["schema"] == 1, "schema"
assert c["enabled"] is False, "enabled"
assert c["dry_run"] is True, "dry_run"
assert c["allowlist"] == [], "allowlist"
assert c["performance_mode"] == "observe", "performance_mode"
assert isinstance(c["failure_limit"], int) and 1 <= c["failure_limit"] <= 10, "failure_limit"
PY
ok 'config/default.json inert defaults'

printf '%s\n' 'Safety baseline passed.'
