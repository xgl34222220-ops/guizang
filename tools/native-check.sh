#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p build/native
CXX=${CXX:-c++}
"$CXX" -std=c++17 -Wall -Wextra -Werror -pedantic tests/proc_test.cpp -o build/native/proc-test
build/native/proc-test
"$CXX" -std=c++17 -Wall -Wextra -Werror -pedantic native/probe.cpp -o build/native/guizang-probe
build/native/guizang-probe --json > build/native/host-probe.json
python3 - <<'PY'
import json
p=json.load(open('build/native/host-probe.json'))
assert p['schema']==2 and p['source']=='guizang-native-probe'
assert p['read_only'] is True and p['android'] is False
assert p['execution']=='disabled' and p['freeze_ready'] is False
assert p['identity']['pid']>1 and int(p['identity']['starttime'])>0
print('Native host JSON contract passed; NOT an Android compatibility result')
PY
if build/native/guizang-probe --json --fixture-pid '1;id' > build/native/rejected.json; then exit 1; fi
if build/native/guizang-probe --enable > build/native/rejected.json; then exit 1; fi
