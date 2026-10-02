#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
for file in module/*.sh tools/*.sh; do sh -n "$file"; done
node --check webroot/app.js
node --check webroot/bridge.js
node --test tests/*.test.cjs
python3 -m compileall -q core tests
# Never accidentally distribute an active module or executable third-party payload.
test ! -e module/post-fs-data.sh
test ! -e module/sepolicy.rule
grep -q '^abort ' module/customize.sh
python3 -c 'import json; c=json.load(open("config/default.json")); assert c["enabled"] is False and c["dry_run"] is True and c["allowlist"] == []'
printf '%s\n' 'Safety defaults, shell syntax, UI tests and Python compilation passed.'
