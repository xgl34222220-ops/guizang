package org.guizang.fixture;

import android.app.Activity;
import android.app.Application;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import android.view.View;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.UUID;

/** Deliberately passive, single-process test app. No Binder heartbeat endpoints. */
public final class MainActivity extends Activity {
    private static FixtureState processState;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView status;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText(processState.display());
            ui.postDelayed(this, FixtureState.DELAY_MS);
        }
    };

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (processState == null) {
            processState = new FixtureState(getFilesDir());
            processState.start();
        }
        processState.mark("onCreate");
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(0xfff6f5f0);
        status = new TextView(this);
        int padding = (int) (24 * getResources().getDisplayMetrics().density);
        status.setPadding(padding, padding, padding, padding);
        status.setTextSize(16);
        status.setTextColor(0xff17232c);
        status.setTextIsSelectable(true);
        scroll.addView(status);
        // API 35 uses edge-to-edge. Keep evidence text clear of system bars.
        scroll.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override public android.view.WindowInsets onApplyWindowInsets(
                    View view, android.view.WindowInsets insets) {
                view.setPadding(insets.getSystemWindowInsetLeft(),
                        insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(),
                        insets.getSystemWindowInsetBottom());
                return insets;
            }
        });
        setContentView(scroll);
        scroll.requestApplyInsets();
        status.setText(processState.display());
    }

    @Override protected void onStart() {
        super.onStart();
        processState.mark("onStart");
    }

    @Override protected void onRestart() {
        super.onRestart();
        processState.mark("onRestart");
    }

    @Override protected void onResume() {
        super.onResume();
        processState.mark("onResume");
        ui.removeCallbacks(refresh);
        ui.post(refresh);
    }

    @Override protected void onPause() {
        ui.removeCallbacks(refresh);
        processState.mark("onPause");
        super.onPause();
    }

    @Override protected void onStop() {
        processState.mark("onStop");
        super.onStop();
    }

    @Override protected void onDestroy() {
        ui.removeCallbacks(refresh);
        processState.mark("onDestroy");
        super.onDestroy();
        // The single daemon thread belongs to the process, not to an Activity.
    }

    private static final class Marker {
        final String name;
        final long sequence;
        final long elapsedMs;

        Marker(String name, long sequence) {
            this.name = name;
            this.sequence = sequence;
            this.elapsedMs = SystemClock.elapsedRealtime();
        }

        JSONObject json() throws JSONException {
            return new JSONObject().put("name", name).put("sequence", sequence)
                    .put("elapsed_realtime_ms", elapsedMs);
        }
    }

    private static final class FixtureState {
        static final long DELAY_MS = 500;
        private static final int MAX_MARKERS = 16;
        private final int pid = Process.myPid();
        private final int uid = Process.myUid();
        private final String nonce = UUID.randomUUID().toString();
        private final String processName = Application.getProcessName();
        private final long processStartMs = Process.getStartElapsedRealtime();
        private final long fixtureStartMs = SystemClock.elapsedRealtime();
        private final String procStartTicks;
        private final long clockTicksPerSecond;
        private final File heartbeat;
        private final File pendingHeartbeat;
        private final ArrayDeque<Marker> markers = new ArrayDeque<>();
        private long counter;
        private long lifecycleSequence;
        private long lastTickMs;
        private long lastTickGapMs;
        private long writeErrors;
        private String lastWriteStatus = "pending";

        FixtureState(File privateFiles) {
            heartbeat = new File(privateFiles, "heartbeat.json");
            pendingHeartbeat = new File(privateFiles, "heartbeat.json.tmp");
            procStartTicks = readStartTicks();
            long ticks;
            try {
                ticks = Os.sysconf(OsConstants._SC_CLK_TCK);
            } catch (Exception error) {
                ticks = -1;
            }
            clockTicksPerSecond = ticks;
        }

        private String readStartTicks() {
            // Read complete contents: comm may legally include newline characters.
            try (FileInputStream input = new FileInputStream("/proc/self/stat")) {
                byte[] bytes = new byte[8192];
                int used = 0;
                while (used < bytes.length) {
                    int count = input.read(bytes, used, bytes.length - used);
                    if (count < 0) return ProcStat.startTicks(
                            new String(bytes, 0, used, StandardCharsets.UTF_8), pid);
                    used += count;
                }
            } catch (IOException | IllegalArgumentException | SecurityException error) {
                // A missing identity field is explicit, never replaced with PID.
            }
            return null;
        }

        synchronized void mark(String name) {
            if (markers.size() == MAX_MARKERS) markers.removeFirst();
            markers.addLast(new Marker(name, ++lifecycleSequence));
        }

        void start() {
            Thread thread = new Thread(new Runnable() {
                @Override public void run() {
                    for (;;) {
                        tickAndWrite();
                        try {
                            // Fixed delay AFTER work. Thaw never replays missed ticks.
                            Thread.sleep(DELAY_MS);
                        } catch (InterruptedException stopped) {
                            Thread.currentThread().interrupt();
                            return;
                        }
                    }
                }
            }, "fixture-heartbeat");
            thread.setDaemon(true);
            thread.start();
        }

        private synchronized JSONObject nextRecord() throws JSONException {
            long now = SystemClock.elapsedRealtime();
            lastTickGapMs = lastTickMs == 0 ? 0 : now - lastTickMs;
            lastTickMs = now;
            ++counter;
            JSONArray recent = new JSONArray();
            for (Marker marker : markers) recent.put(marker.json());
            return new JSONObject()
                    .put("schema_version", 1)
                    .put("package", "org.guizang.fixture")
                    .put("process_name", processName)
                    .put("pid", pid).put("uid", uid)
                    .put("nonce", nonce)
                    .put("starttime", procStartTicks == null
                            ? JSONObject.NULL : procStartTicks)
                    .put("clock_ticks_per_second", clockTicksPerSecond)
                    .put("process_start_elapsed_realtime_ms", processStartMs)
                    .put("fixture_start_elapsed_realtime_ms", fixtureStartMs)
                    .put("elapsedRealtimeMs", now)
                    .put("process_age_ms", now - processStartMs)
                    .put("fixture_age_ms", now - fixtureStartMs)
                    .put("counter", counter)
                    .put("fixed_delay_ms", DELAY_MS)
                    .put("last_tick_gap_ms", lastTickGapMs)
                    .put("lifecycle_sequence", lifecycleSequence)
                    .put("lifecycle", recent)
                    .put("prior_write_errors", writeErrors);
        }

        private void tickAndWrite() {
            try {
                byte[] bytes = nextRecord().toString().getBytes(StandardCharsets.UTF_8);
                // A same-directory rename keeps external readers from seeing a
                // partial record on every supported API (including Android 28).
                try (FileOutputStream output = new FileOutputStream(pendingHeartbeat)) {
                    Os.fchmod(output.getFD(), 0600);
                    output.write(bytes);
                    output.getFD().sync();
                }
                Os.rename(pendingHeartbeat.getAbsolutePath(), heartbeat.getAbsolutePath());
                synchronized (this) { lastWriteStatus = "ok"; }
            } catch (Exception error) {
                // Leave the previous base record intact; retry at the usual delay.
                pendingHeartbeat.delete();
                synchronized (this) {
                    ++writeErrors;
                    lastWriteStatus = "failed (" + error.getClass().getSimpleName() + ")";
                }
                // No logcat, user inputs, unbounded error log or retry burst.
            }
        }

        synchronized String display() {
            StringBuilder text = new StringBuilder("GUIZANG DISPOSABLE FIXTURE\n\n")
                    .append("VM-only research target. No real-device validation yet.\n")
                    .append("No permissions or services. Background execution is best-effort; ")
                    .append("Android may suspend or kill this process. A stalled counter alone ")
                    .append("does not prove Guizang froze it.\n\n")
                    .append("Package / process: ").append(processName)
                    .append("\nPID: ").append(pid).append("   UID: ").append(uid)
                    .append("\nProcess nonce: ").append(nonce)
                    .append("\n/proc start ticks: ").append(procStartTicks)
                    .append("\nProcess start elapsed ms: ").append(processStartMs)
                    .append("\nBoot elapsed ms: ").append(SystemClock.elapsedRealtime())
                    .append("\nHeartbeat counter: ").append(counter)
                    .append("\nLast tick gap ms: ").append(lastTickGapMs)
                    .append("\nPrivate heartbeat file: files/heartbeat.json")
                    .append("\nLast write: ").append(lastWriteStatus)
                    .append("   Errors: ").append(writeErrors)
                    .append("\n\nRecent lifecycle markers (newest last):\n");
            for (Marker marker : markers) {
                text.append(marker.sequence).append(" ").append(marker.name)
                        .append(" @ ").append(marker.elapsedMs).append(" ms\n");
            }
            return text.toString();
        }
    }
}
