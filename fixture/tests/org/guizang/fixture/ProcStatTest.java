package org.guizang.fixture;

/** Host-side parser tests only; not a claim of Android runtime validation. */
public final class ProcStatTest {
    private static String stat(String comm, String ticks) {
        StringBuilder data = new StringBuilder("123 (").append(comm).append(") S");
        for (int field = 4; field <= 21; ++field) data.append(" ").append(field);
        return data.append(" ").append(ticks).append(" 23 24\n").toString();
    }

    private static void check(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }

    private static void invalid(String value, int pid) {
        try {
            ProcStat.startTicks(value, pid);
            throw new AssertionError("Accepted malformed stat");
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    public static void main(String[] args) {
        check("999", ProcStat.startTicks(stat("fixture", "999"), 123));
        check("42", ProcStat.startTicks(stat("has spaces (and) ) trailing", "42"), 123));
        check("0", ProcStat.startTicks(stat("new\nline ) (", "0"), 123));
        check("18446744073709551615", ProcStat.startTicks(
                stat("fixture", "18446744073709551615"), 123));
        invalid(null, 123);
        invalid("123 bad S 1 2 3", 123);
        invalid("123 (bad)S 1 2 3", 123);
        invalid("123 (bad) S 1 2 3", 123);
        invalid(stat("fixture", "-3"), 123);
        invalid(stat("fixture", "nan"), 123);
        invalid(stat("fixture", "10"), 456);
        invalid(stat("fixture", "10").replaceFirst("123", "0"), 0);
        System.out.println("ProcStatTest: 12 checks passed (host JVM only).");
    }
}
