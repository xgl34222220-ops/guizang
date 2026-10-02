package org.guizang.fixture;

/** Pure Java parser: comm (field 2) may contain spaces, newlines and parentheses. */
final class ProcStat {
    private ProcStat() {}

    static String startTicks(String stat, int expectedPid) {
        if (stat == null) throw new IllegalArgumentException("Missing stat");
        int open = stat.indexOf('(');
        int close = stat.lastIndexOf(')');
        if (open < 1 || close <= open || close + 1 >= stat.length()
                || !Character.isWhitespace(stat.charAt(close + 1))) {
            throw new IllegalArgumentException("Malformed stat comm");
        }
        int actualPid;
        try {
            actualPid = Integer.parseInt(stat.substring(0, open).trim());
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("Malformed stat pid", error);
        }
        if (actualPid != expectedPid || actualPid <= 0) {
            throw new IllegalArgumentException("Unexpected stat pid");
        }
        // After the LAST ')' the first token is state (field 3). starttime is 22.
        String[] fields = stat.substring(close + 1).trim().split("\\s+");
        if (fields.length < 20 || fields[0].length() != 1
                || !fields[19].matches("[0-9]+")) {
            throw new IllegalArgumentException("Missing or malformed starttime");
        }
        // Preserve integer precision when consumers use JSON/JavaScript.
        return fields[19];
    }
}
