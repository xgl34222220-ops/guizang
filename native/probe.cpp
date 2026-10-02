// Read-only Android/host diagnostic. No write, ioctl, signal, property mutation or shell execution.
#include "proc.hpp"
#include <cerrno>
#include <climits>
#include <fcntl.h>
#include <iostream>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#include <unistd.h>
#ifdef __ANDROID__
#include <sys/system_properties.h>
#endif

namespace {
class Fd {
public:
    explicit Fd(int value) : value_(value) {}
    ~Fd() { if (value_ >= 0) close(value_); }
    Fd(const Fd&) = delete;
    Fd& operator=(const Fd&) = delete;
    int get() const { return value_; }
private: int value_;
};
std::optional<std::string> read_at(int directory, const std::string& path) {
    Fd fd(openat(directory, path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
    if (fd.get() < 0) return std::nullopt;
    std::string out; char buffer[4096];
    for (;;) {
        ssize_t count = read(fd.get(), buffer, sizeof(buffer));
        if (count == 0) return out;
        if (count < 0) { if (errno == EINTR) continue; return std::nullopt; }
        if (out.size() + static_cast<size_t>(count) > 65536) return std::nullopt;
        out.append(buffer, static_cast<size_t>(count));
    }
}
bool readable_regular(const std::string& path) {
    struct stat st{};
    return lstat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode) && access(path.c_str(), R_OK) == 0;
}
bool exists(const char* path) { struct stat st{}; return stat(path, &st) == 0; }
std::string property(const char* key) {
#ifdef __ANDROID__
    char value[PROP_VALUE_MAX]{};
    if (__system_property_get(key, value) > 0) return value;
#else
    (void)key;
#endif
    return "unknown";
}
struct Identity { uint64_t uid; uint64_t start; };
std::optional<Identity> identity(int directory) {
    const auto s = read_at(directory, "stat"), u = read_at(directory, "status");
    if (!s || !u) return std::nullopt;
    const auto start = guizang::starttime(*s), uid = guizang::uid(*u);
    if (!start || !uid || *start == 0) return std::nullopt;
    return Identity{*uid, *start};
}
void error(const char* code) {
    std::cout << "{\"schema\":2,\"source\":\"guizang-native-probe\",\"read_only\":true,\"error\":"
              << guizang::json_escape(code) << "}\n";
}
}
int main(int argc, char** argv) {
    // --fixture-pid is ONLY for the disposable fixture. WebUI never supplies arguments.
    pid_t pid = getpid(); bool fixture = false;
    if (argc == 4 && std::string(argv[1]) == "--json" && std::string(argv[2]) == "--fixture-pid") {
        auto n = guizang::unsigned_number(argv[3]);
        if (!n || *n < 2 || *n > INT_MAX) { error("invalid_fixture_pid"); return 2; }
        pid = static_cast<pid_t>(*n); fixture = true;
    } else if (argc != 2 || std::string(argv[1]) != "--json") {
        error("unsupported_arguments"); return 2;
    }
    const std::string proc = "/proc/" + std::to_string(pid);
    Fd directory(open(proc.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW));
    if (directory.get() < 0) { error("process_unavailable"); return 3; }
    auto before = identity(directory.get());
    if (!before) { error("identity_unavailable"); return 3; }
    if (fixture) {
        auto name = read_at(directory.get(), "cmdline");
        if (!name || name->substr(0, name->find('\0')) != "org.guizang.fixture"
                || before->uid < 10000 || before->uid >= 20000) {
            error("not_allowed_fixture"); return 4;
        }
    }
    const auto group = read_at(directory.get(), "cgroup");
    const auto unified = group ? guizang::unified_path(*group) : std::nullopt;
    // Resolve the actual existing cgroup2 mount; never migrate/create a hierarchy.
    const auto mounts = read_at(AT_FDCWD, "/proc/self/mountinfo");
    const auto mapped = (unified && mounts) ? guizang::freezer_path(*mounts, *unified) : std::nullopt;
    const std::string node = mapped ? *mapped : "";
    const bool freezer_node = !node.empty() && readable_regular(node);
    const auto freeze_request = freezer_node ? read_at(AT_FDCWD, node) : std::nullopt;
    const auto events = freezer_node ? read_at(AT_FDCWD, node.substr(0, node.rfind('/')) + "/cgroup.events") : std::nullopt;
    const auto frozen = events ? guizang::frozen_event(*events) : std::nullopt;
    bool pidfd_observed = false;
#ifdef SYS_pidfd_open
    Fd pidfd(static_cast<int>(syscall(SYS_pidfd_open, pid, 0)));
    pidfd_observed = pidfd.get() >= 0;
#endif
    auto after = identity(directory.get());
    if (!after || before->uid != after->uid || before->start != after->start) {
        error("identity_changed"); return 3;
    }
    auto boot = read_at(AT_FDCWD, "/proc/sys/kernel/random/boot_id");
    if (boot && !boot->empty() && boot->back() == '\n') boot->pop_back();
    struct utsname kernel{}; const bool kernel_ok = uname(&kernel) == 0;
    const auto q = guizang::json_escape;
#ifdef __ANDROID__
    constexpr const char* android = "true";
#else
    constexpr const char* android = "false";
#endif
    // Binder node presence and pidfd availability are observations, NOT freeze readiness.
    std::cout << "{\"schema\":2,\"source\":\"guizang-native-probe\",\"read_only\":true,"
              << "\"android\":" << android << ",\"effective_uid\":" << geteuid()
              << ",\"sdk\":" << q(property("ro.build.version.sdk"))
              << ",\"model\":" << q(property("ro.product.model"))
              << ",\"soc\":" << q(property("ro.soc.model"))
              << ",\"kernel\":" << q(kernel_ok ? kernel.release : "unknown")
              << ",\"identity\":{\"pid\":" << pid << ",\"uid\":" << before->uid
              << ",\"boot_id\":" << q(boot ? *boot : "unknown")
              << ",\"starttime\":\"" << before->start << "\",\"fixture\":" << (fixture ? "true" : "false") << "}"
              << ",\"capabilities\":{\"cgroup2_membership\":" << (unified ? "true" : "false")
              << ",\"self_freezer_node\":" << (freezer_node ? "true" : "false")
              << ",\"binder_node\":" << ((exists("/dev/binder") || exists("/dev/binderfs/binder")) ? "true" : "false")
              << ",\"pidfd_open\":" << (pidfd_observed ? "true" : "false")
              << ",\"framework_coordinator\":false,\"protection_signals\":false,\"verified_thaw\":false}"
              << ",\"freezer_observation\":{\"requested\":" << (freeze_request && *freeze_request == "1\n" ? "true" : freeze_request && *freeze_request == "0\n" ? "false" : "null")
              << ",\"complete\":" << (frozen ? (*frozen ? "true" : "false") : "null") << "}"
              << ",\"execution\":\"disabled\",\"freeze_ready\":false,"
              << "\"blockers\":[\"framework_coordinator_unverified\",\"protection_signals_unknown\",\"device_thaw_unverified\"]}\n";
    return 0;
}
