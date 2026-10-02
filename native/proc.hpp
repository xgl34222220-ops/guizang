#pragma once
#include <charconv>
#include <cstdint>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace guizang {
inline std::optional<uint64_t> unsigned_number(std::string_view text) {
    uint64_t result{};
    if (text.empty()) return std::nullopt;
    auto parsed = std::from_chars(text.data(), text.data() + text.size(), result);
    if (parsed.ec != std::errc() || parsed.ptr != text.data() + text.size()) return std::nullopt;
    return result;
}
inline std::optional<uint64_t> starttime(const std::string& stat) {
    // comm may contain spaces and ')' characters; fields resume after the LAST ')'.
    auto close = stat.rfind(')');
    auto open = stat.find('(');
    if (open == std::string::npos || close == std::string::npos || close <= open) return std::nullopt;
    std::istringstream fields(stat.substr(close + 1));
    std::string token;
    for (int field = 3; field <= 22; ++field) {
        if (!(fields >> token)) return std::nullopt;
        if (field == 22) return unsigned_number(token);
    }
    return std::nullopt;
}
inline std::optional<uint64_t> uid(const std::string& status) {
    std::istringstream lines(status); std::string line;
    while (std::getline(lines, line)) {
        if (line.rfind("Uid:\t", 0) == 0 || line.rfind("Uid: ", 0) == 0) {
            std::istringstream values(line.substr(4));
            std::string real, effective;
            if (!(values >> real >> effective)) return std::nullopt;
            auto r = unsigned_number(real), e = unsigned_number(effective);
            if (!r || !e || r != e) return std::nullopt;
            return r;
        }
    }
    return std::nullopt;
}
inline bool safe_absolute(const std::string& path) {
    if (path.empty() || path[0] != '/' || path.find('\0') != std::string::npos) return false;
    std::istringstream parts(path); std::string part;
    while (std::getline(parts, part, '/')) if (part == "." || part == "..") return false;
    return true;
}
inline std::optional<std::string> unified_path(const std::string& cgroup) {
    std::istringstream lines(cgroup); std::string line;
    while (std::getline(lines, line)) {
        if (line.rfind("0::", 0) == 0 && safe_absolute(line.substr(3))) return line.substr(3);
    }
    return std::nullopt;
}
inline std::optional<std::string> freezer_path(const std::string& mountinfo, const std::string& group) {
    if (!safe_absolute(group)) return std::nullopt;
    std::istringstream lines(mountinfo); std::string line;
    std::optional<std::string> result; size_t best = 0;
    while (std::getline(lines, line)) {
        const auto divider = line.find(" - ");
        if (divider == std::string::npos) continue;
        std::istringstream post(line.substr(divider + 3)); std::string fs;
        post >> fs; if (fs != "cgroup2") continue;
        std::istringstream pre(line.substr(0, divider));
        std::string id, parent, device, root, mount;
        if (!(pre >> id >> parent >> device >> root >> mount)) continue;
        // Escaped mount paths are uncommon here; fail closed rather than guessing.
        if (!safe_absolute(root) || !safe_absolute(mount) || root.find('\\') != std::string::npos
                || mount.find('\\') != std::string::npos) continue;
        const bool within = root == "/" || group == root || group.rfind(root + "/", 0) == 0;
        if (!within || root.size() < best) continue;
        std::string suffix = root == "/" ? group : group.substr(root.size());
        if (suffix == "/") suffix.clear();
        result = (mount == "/" ? "" : mount) + suffix + "/cgroup.freeze";
        best = root.size();
    }
    return result;
}
inline std::optional<bool> frozen_event(const std::string& events) {
    std::istringstream lines(events); std::string key, value;
    while (lines >> key >> value) if (key == "frozen") {
        if (value == "0") return false;
        if (value == "1") return true;
        return std::nullopt;
    }
    return std::nullopt;
}
inline std::string json_escape(const std::string& value) {
    static const char hex[] = "0123456789abcdef";
    std::string out = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
        else if (c < 0x20) { out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
        else out += static_cast<char>(c);
    }
    return out + '"';
}
} // namespace guizang
