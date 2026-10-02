#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
NDK=${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-}}
if [ -z "$NDK" ]; then printf '%s\n' 'Set ANDROID_NDK_HOME to an installed official Android NDK.' >&2; exit 2; fi
TC="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
mkdir -p build/android/arm64-v8a build/android/x86_64
for abi in arm64-v8a x86_64; do
  case "$abi" in arm64-v8a) target=aarch64-linux-android;; x86_64) target=x86_64-linux-android;; esac
  compiler="$TC/${target}28-clang++"
  [ -x "$compiler" ] || { printf 'Missing NDK compiler: %s\n' "$compiler" >&2; exit 2; }
  "$compiler" -std=c++17 -O2 -Wall -Wextra -Werror -fPIE -pie -static-libstdc++ \
    native/probe.cpp -o "build/android/$abi/guizang-probe"
done
cat "$NDK/source.properties" > build/android/ndk-version.txt
sha256sum build/android/*/guizang-probe > build/android/SHA256SUMS
printf '%s\n' 'Compiled read-only Android probe. No device execution or compatibility claim.'
