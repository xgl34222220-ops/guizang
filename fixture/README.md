# Disposable Android heartbeat fixture

**VM-only research fixture. No Android runtime or device validation has been
performed.** This is a passive APK for future explicitly authorized disposable-VM
experiments; it does not install itself, freeze anything, request Root, or change
Android settings. Root, fixture installation and freeze/thaw tests remain separate
authorization gates.

## Boundaries

- Package and sole configured process: `org.guizang.fixture`.
- One exported launcher Activity; no services, receivers, providers, shared UID,
  native libraries, secondary processes, or requested Android permissions.
- No network, audio, accessibility, VPN, public/external storage, wake locks or
  alarms. No analytics or logcat writes. Launch intents are not inspected.
- `debuggable=true`, `testOnly=true`, `allowBackup=false`, `minSdk=28`,
  `targetSdk=35`. Never use on a personal or production device.
- A process-local singleton owns one daemon heartbeat thread. Backgrounding or
  recreating the Activity does not intentionally stop or duplicate that thread.
  No foreground/background service is used to keep the app alive.

## Host-only build

From the repository root:

```sh
sh tools/build-fixture.sh
```

The script honors `JAVA_HOME` or finds the JDK from `javac` on `PATH`; it honors
`ANDROID_SDK_ROOT` or `ANDROID_HOME`. If absent, the existing sibling
`android-build-tools/` JDK 21 and SDK are optional local fallbacks. It chooses the
latest installed stable build-tools and platform API 35+; pin `ANDROID_PLATFORM`
and `ANDROID_BUILD_TOOLS_VERSION` for reproducibility. The locally verified pair
is `android-37.0` and `36.0.0`. JDK 17+ and Python 3 are required. No Gradle,
dependency downloads or device commands run.

Outputs under ignored `build/fixture/`:

- `guizang-fixture-debug.apk`: aligned APK, signed with a newly generated disposable test
  key. **Never redistribute any signing key.** Keys/passwords are created only in
  a private temporary subdirectory of `fixture/build/` outside the distributable
  APK directory, then discarded on exit. An abrupt
  kill/power loss may leave that ignored directory; treat it as private build data.
- `unsigned-aligned.apk`: stable ZIP metadata for reproducibility comparison when
  source and toolchain are unchanged. Fresh per-build keys necessarily change
  the signed APK's certificate and hash. A previous installation signed by a
  different build cannot be upgraded in place; do not bypass that restriction.
- `build-info.txt`, `signature-verification.txt`, `apk-badging.txt`,
  `apk-permissions.txt`, `apk-manifest.txt`: host verification evidence.

The build compiles and runs 12 host-side parser checks, verifies manifest
boundaries, compiles Java/Dex, inspects compiled SDK/package/permission metadata,
and verifies signature/alignment. These checks **do not validate runtime behavior
on Android**. This fixture is test-only and deliberately not a production-signed
release.

## Evidence without contacting the app over Binder

The app atomically replaces its small private `files/heartbeat.json` approximately
every 500 ms using a synced, closed, mode-`0600` temporary file followed by a
same-directory atomic rename. An authorized external observer
can read this file via a disposable VM's `run-as` or Root shell without invoking an
Activity, content provider, service or other Binder interface in the target.
Read the **base JSON file**; ignore `heartbeat.json.tmp`.
During initial startup it may not exist yet. A failed replacement retains
the previous complete record, so file staleness is not by itself freeze evidence.

The heartbeat is fixed-delay: one tick and one bounded snapshot write, followed
by a 500 ms sleep. There is no catch-up burst after a scheduling gap. One JSON
snapshot contains at most 16 lifecycle markers and replaces the previous one;
it is not an append-only log. No user input is recorded.

| Field | Meaning |
| --- | --- |
| `schema_version` | Currently 1 |
| `package`, `process_name`, `pid`, `uid` | Explicit target metadata; PID is **not** a stable identity |
| `nonce` | Random per-process UUID; activity recreation keeps it; process restart changes it |
| `starttime` | `/proc/self/stat` field 22 as an exact decimal string, or JSON null if unavailable |
| `clock_ticks_per_second` | `_SC_CLK_TCK`, or -1 if unavailable |
| `process_start_elapsed_realtime_ms` | Android's process start elapsed time |
| `fixture_start_elapsed_realtime_ms` | First fixture initialization elapsed time |
| `elapsedRealtimeMs` | Monotonic boot-relative clock, including deep sleep |
| `process_age_ms`, `fixture_age_ms` | Cumulative elapsed ages at the tick; not CPU time |
| `counter` | Strictly increasing for tick attempts within one process |
| `fixed_delay_ms` | 500 ms sleep after each write attempt |
| `last_tick_gap_ms` | Elapsed time since the previous tick; first tick uses 0 |
| `lifecycle_sequence`, `lifecycle` | Monotonic sequence plus latest 16 callback names/timestamps |
| `prior_write_errors` | Failed write attempts before this snapshot, exposed on next successful write |

The UI shows PID, UID, process nonce/start evidence, current boot elapsed clock,
counter, write status, and lifecycle markers. Its refresh callback runs only while
resumed. Disk writes belong to the separate daemon thread.

`/proc/self/stat` parsing uses the final closing parenthesis before splitting the
remaining fields; the comm field may contain spaces, newlines, or parentheses.
The host test covers those cases, truncated/invalid records, PID mismatch, and
integer precision. A missing start field is explicitly null, never replaced by a
PID guess.

## Interpretation and limits

- Compare PID **with** process start identity and nonce. Preserve samples outside
  the app if restart detection matters: a restarted process overwrites the old
  snapshot and resets its counter. No crash history is persisted internally.
- A changed nonce is evidence of a new fixture process, not proof of why it
  restarted. Android is not guaranteed to call `onDestroy` when killing a process.
- A flat counter alone is inconclusive: Android cached-app freezing, scheduling,
  deep sleep, process death or write failure can also cause it. Background
  heartbeats are best-effort and not guaranteed on Android 35.
- After thaw, the same nonce/start identity and advancing counter, together with
  a large monotonic gap, can support continuity evidence. Re-check live process
  identity and independently verified cgroup/Binder state before drawing a freeze
  conclusion. The fixture itself does not inspect or change freezer state.
- The snapshot remains on disk if the process dies. Do not interpret an existing
  file as proof the process is currently alive.
- No wake lock, reboot persistence, automatic launch, self-restart, exported
  diagnostic API, tamper protection or production-device safety guarantee exists.
