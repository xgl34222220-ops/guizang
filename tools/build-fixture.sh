#!/bin/sh
# Offline, host-only build. This script never invokes adb or any device command.
set -eu
umask 077
export LC_ALL=C TZ=UTC
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FIXTURE="$ROOT/fixture"
LOCAL_TOOLS="$ROOT/../android-build-tools"
die() { printf 'Fixture build failed: %s\n' "$*" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || die 'python3 is required'
if test -z "${JAVA_HOME:-}"; then
    if command -v javac >/dev/null 2>&1; then
        JAVA_HOME=$(python3 -c 'import os, shutil; print(os.path.dirname(os.path.dirname(os.path.realpath(shutil.which("javac")))))')
    else
        JAVA_HOME="$LOCAL_TOOLS/jdk-21.0.12.1+1"
    fi
fi
ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-"$LOCAL_TOOLS/sdk"}}
if test -z "${ANDROID_BUILD_TOOLS_VERSION:-}"; then
    ANDROID_BUILD_TOOLS_VERSION=$(python3 - "$ANDROID_SDK_ROOT" <<'PY'
from pathlib import Path
import re
import sys
versions = [p.name for p in (Path(sys.argv[1]) / 'build-tools').glob('*')
            if p.is_dir() and re.fullmatch(r'\d+\.\d+\.\d+', p.name)]
if not versions:
    sys.exit('No stable Android build-tools installed; set ANDROID_BUILD_TOOLS_VERSION.')
print(max(versions, key=lambda v: tuple(map(int, v.split('.')))))
PY
    )
fi
if test -z "${ANDROID_PLATFORM:-}"; then
    ANDROID_PLATFORM=$(python3 - "$ANDROID_SDK_ROOT" <<'PY'
from pathlib import Path
import re
import sys
platforms = []
for path in (Path(sys.argv[1]) / 'platforms').glob('android-*'):
    match = re.fullmatch(r'android-(\d+)(?:\.(\d+))?', path.name)
    if match and int(match[1]) >= 35 and (path / 'android.jar').is_file():
        platforms.append((int(match[1]), int(match[2] or 0), path.name))
if not platforms:
    sys.exit('No Android platform API 35+ installed; set ANDROID_PLATFORM.')
print(max(platforms)[2])
PY
    )
fi
BUILD_TOOLS="$ANDROID_SDK_ROOT/build-tools/$ANDROID_BUILD_TOOLS_VERSION"
ANDROID_JAR="$ANDROID_SDK_ROOT/platforms/$ANDROID_PLATFORM/android.jar"
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
export PATH

for tool in java javac keytool jar; do
    test -x "$JAVA_HOME/bin/$tool" || die "missing $JAVA_HOME/bin/$tool"
done
for tool in aapt d8 zipalign apksigner; do
    test -x "$BUILD_TOOLS/$tool" || die "missing $BUILD_TOOLS/$tool"
done
test -r "$ANDROID_JAR" || die "missing $ANDROID_JAR"
BUILD="$ROOT/build/fixture"
mkdir -p "$BUILD" "$FIXTURE/build"
# Key material is outside the distributable APK directory, still ignored build/.
RUN=$(mktemp -d "$FIXTURE/build/run.XXXXXXXX")
# Remove ONLY this invocation's temporary build directory, including its test key.
trap 'rm -rf -- "$RUN"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$RUN/classes" "$RUN/test-classes" "$RUN/dex"

# Fail closed if someone adds a permission, component or process to the fixture.
python3 - "$FIXTURE/AndroidManifest.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
a = '{http://schemas.android.com/apk/res/android}'
assert root.attrib['package'] == 'org.guizang.fixture'
assert a + 'sharedUserId' not in root.attrib
assert sorted(child.tag for child in root) == ['application', 'uses-sdk']
sdk = root.find('uses-sdk')
assert sdk.get(a + 'minSdkVersion') == '28'
assert sdk.get(a + 'targetSdkVersion') == '35'
app = root.find('application')
assert app.get(a + 'process') == 'org.guizang.fixture'
assert app.get(a + 'debuggable') == 'true'
assert app.get(a + 'testOnly') == 'true'
assert app.get(a + 'allowBackup') == 'false'
assert app.get(a + 'usesCleartextTraffic') == 'false'
assert [child.tag for child in app] == ['activity']
activity = app.find('activity')
assert activity.get(a + 'name') == '.MainActivity'
assert a + 'process' not in activity.attrib
assert all(node.tag not in {'uses-permission', 'uses-permission-sdk-23', 'service',
                            'receiver', 'provider', 'activity-alias'} for node in root.iter())
print('Manifest source safety checks passed.')
PY

"$JAVA_HOME/bin/javac" --release 8 -d "$RUN/test-classes" \
    "$FIXTURE/src/org/guizang/fixture/ProcStat.java" \
    "$FIXTURE/tests/org/guizang/fixture/ProcStatTest.java"
"$JAVA_HOME/bin/java" -cp "$RUN/test-classes" org.guizang.fixture.ProcStatTest

"$JAVA_HOME/bin/javac" -encoding UTF-8 -source 8 -target 8 \
    -bootclasspath "$ANDROID_JAR" -d "$RUN/classes" \
    "$FIXTURE/src/org/guizang/fixture/ProcStat.java" \
    "$FIXTURE/src/org/guizang/fixture/MainActivity.java"
"$JAVA_HOME/bin/jar" --create --file "$RUN/classes.jar" \
    --date=2026-10-02T00:00:00Z -C "$RUN/classes" .
"$BUILD_TOOLS/d8" --min-api 28 --lib "$ANDROID_JAR" \
    --output "$RUN/dex" "$RUN/classes.jar"
"$BUILD_TOOLS/aapt" package -f -M "$FIXTURE/AndroidManifest.xml" \
    -I "$ANDROID_JAR" -F "$RUN/resources.apk"

# Stable unsigned bytes with fixed ZIP metadata. Signing intentionally uses a new
# disposable key each run, so signed APK hashes and certificates differ per build.
python3 - "$RUN/resources.apk" "$RUN/dex/classes.dex" "$RUN/unsigned.apk" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as resources:
    entries = {name: resources.read(name) for name in resources.namelist()}
with open(sys.argv[2], 'rb') as dex:
    entries['classes.dex'] = dex.read()
with zipfile.ZipFile(sys.argv[3], 'w') as output:
    for name, content in sorted(entries.items()):
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        output.writestr(info, content, compresslevel=9)
PY
"$BUILD_TOOLS/zipalign" -p -f 4 "$RUN/unsigned.apk" "$RUN/unsigned-aligned.apk"

# Fresh random local-only credentials; never reuse production keys or copy keys
# outside build/. These files are destroyed by the EXIT trap on success/failure.
python3 - "$RUN/test-key-password" <<'PY'
import secrets
import sys
with open(sys.argv[1], 'x', encoding='ascii') as password:
    password.write(secrets.token_urlsafe(32) + '\n')
PY
"$JAVA_HOME/bin/keytool" -genkeypair -noprompt -keystore "$RUN/test.keystore" \
    -storetype PKCS12 -storepass:file "$RUN/test-key-password" \
    -alias disposable-fixture -keyalg RSA -keysize 2048 -validity 30 \
    -dname 'CN=Guizang Disposable VM Fixture, OU=Test Only, O=Guizang'
"$BUILD_TOOLS/apksigner" sign --ks "$RUN/test.keystore" \
    --ks-key-alias disposable-fixture --ks-pass "file:$RUN/test-key-password" \
    --min-sdk-version 28 --v1-signing-enabled false --v2-signing-enabled true \
    --v3-signing-enabled true --v4-signing-enabled false \
    --out "$RUN/guizang-fixture-debug.apk" "$RUN/unsigned-aligned.apk"
"$BUILD_TOOLS/apksigner" verify --min-sdk-version 28 --verbose \
    "$RUN/guizang-fixture-debug.apk" > "$RUN/signature-verification.txt"
"$BUILD_TOOLS/zipalign" -c -p 4 "$RUN/guizang-fixture-debug.apk"
"$BUILD_TOOLS/aapt" dump badging "$RUN/guizang-fixture-debug.apk" > "$RUN/apk-badging.txt"
"$BUILD_TOOLS/aapt" dump permissions "$RUN/guizang-fixture-debug.apk" > "$RUN/apk-permissions.txt"
"$BUILD_TOOLS/aapt" dump xmltree "$RUN/guizang-fixture-debug.apk" AndroidManifest.xml \
    > "$RUN/apk-manifest.txt"
if grep -q 'uses-permission' "$RUN/apk-permissions.txt"; then
    die 'compiled APK unexpectedly requests a permission'
fi
grep -q "package: name='org.guizang.fixture'" "$RUN/apk-badging.txt" \
    || die 'compiled package mismatch'
grep -q "sdkVersion:'28'" "$RUN/apk-badging.txt" || die 'compiled minimum SDK mismatch'
grep -q "targetSdkVersion:'35'" "$RUN/apk-badging.txt" || die 'compiled target SDK mismatch'

python3 - "$RUN" "$BUILD_TOOLS" "$ANDROID_JAR" "$JAVA_HOME" "$FIXTURE" <<'PY'
import hashlib
from pathlib import Path
import sys
import subprocess

run, tools, android_jar = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
jdk, fixture = Path(sys.argv[4]), Path(sys.argv[5])
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

with (run / 'build-info.txt').open('w', encoding='utf-8') as out:
    out.write('Guizang VM-only disposable fixture; Android runtime NOT validated.\n')
    out.write('Package/process: org.guizang.fixture; minSdk=28; targetSdk=35\n')
    out.write('No device commands performed by this build.\n')
    out.write('Fresh per-build test key discarded; signed APKs are not byte-reproducible.\n')
    out.write(subprocess.run([str(jdk / 'bin/java'), '-version'],
                            capture_output=True, text=True, check=True).stderr)
    out.write(f'Build-tools: {tools.name}; platform: {android_jar.parent.name}\n')
    for path in [run / 'unsigned-aligned.apk', run / 'guizang-fixture-debug.apk', android_jar,
                 tools / 'lib/d8.jar', tools / 'aapt', tools / 'zipalign']:
        out.write(f'{digest(path)}  {path.name}\n')
    for path in [fixture / 'AndroidManifest.xml', *sorted((fixture / 'src').rglob('*.java'))]:
        out.write(f'{digest(path)}  fixture/{path.relative_to(fixture)}\n')
PY

# Publish only after all checks pass. No key or password is an output artifact.
for name in guizang-fixture-debug.apk unsigned-aligned.apk build-info.txt \
            signature-verification.txt apk-badging.txt apk-permissions.txt apk-manifest.txt; do
    mv -f "$RUN/$name" "$BUILD/$name"
done
printf '\n%s\n' "Built and verified: $BUILD/guizang-fixture-debug.apk"
printf '%s\n' 'Host compilation, parser checks, APK signature and alignment passed.'
printf '%s\n' 'No Android runtime/device validation performed. No test key retained.'
