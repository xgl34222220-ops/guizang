#include "../native/proc.hpp"
#include <cassert>
#include <iostream>
int main() {
    std::string stat = "42 (name has ) spaces)) S";
    for(int i=4;i<=21;++i) stat += " 0";
    stat += " 123456789 0 0";
    assert(guizang::starttime(stat) == 123456789);
    assert(!guizang::starttime("42 (a) S 1 2"));
    assert(!guizang::starttime("42 a S 0"));
    assert(!guizang::unsigned_number("-1"));
    assert(!guizang::unsigned_number("42;echo"));
    assert(!guizang::unsigned_number("18446744073709551616"));
    assert(guizang::uid("Name:\tx\nUid:\t10123\t10123\t10123\t10123\n") == 10123);
    assert(!guizang::uid("Uid:\t10123\t0\t10123\t10123\n"));
    assert(!guizang::uid("XUid:\t10123\t10123\n"));
    assert(guizang::unified_path("3:cpu:/x\n0::/uid_10123/pid_42\n") == "/uid_10123/pid_42");
    assert(!guizang::unified_path("0::/../other\n"));
    assert(!guizang::unified_path("0::relative\n"));
    assert(guizang::json_escape("a\n\"b\\") == "\"a\\u000a\\\"b\\\\\"");
    assert(guizang::freezer_path("29 23 0:26 / /dev/cg rw - cgroup2 cgroup rw", "/uid_10/pid_22") == "/dev/cg/uid_10/pid_22/cgroup.freeze");
    assert(guizang::freezer_path("29 23 0:26 /uid_10 /sys/group rw - cgroup2 cgroup rw", "/uid_10/pid_22") == "/sys/group/pid_22/cgroup.freeze");
    assert(!guizang::freezer_path("29 23 0:26 /uid_10 /sys/group rw - cgroup2 cgroup rw", "/uid_100/pid_22"));
    assert(!guizang::freezer_path("29 23 0:26 / /sys/group rw - cgroup cgroup rw", "/uid_10"));
    assert(guizang::frozen_event("populated 1\nfrozen 1\n") == true);
    assert(guizang::frozen_event("populated 1\nfrozen 0\n") == false);
    assert(!guizang::frozen_event("populated 1\n"));
    assert(!guizang::frozen_event("frozen 2\n"));
    // A realistic Android mountinfo can be far larger than 64 KiB; the matching cgroup2
    // line near the end must still resolve (the probe's reader cap is kMountinfoRead).
    std::string big;
    for (int i = 0; big.size() < 200 * 1024; ++i)
        big += std::to_string(100 + i) + " 23 253:5 / /apex/com.android.mod" + std::to_string(i)
             + "@1 ro,nodev,noatime - ext4 /dev/block/dm-5 ro,seclabel\n";
    assert(big.size() > guizang::kSmallProcRead && big.size() < guizang::kMountinfoRead);
    big += "29 23 0:26 / /sys/fs/cgroup rw - cgroup2 none rw\n";
    assert(guizang::freezer_path(big, "/uid_10123/pid_42") == "/sys/fs/cgroup/uid_10123/pid_42/cgroup.freeze");
    // The most specific root wins regardless of line order.
    const std::string nested = "30 23 0:26 /uid_10 /nested rw - cgroup2 c rw\n29 23 0:26 / /sys/fs/cgroup rw - cgroup2 c rw\n";
    assert(guizang::freezer_path(nested, "/uid_10/pid_7") == "/nested/pid_7/cgroup.freeze");
    std::cout << "25 native parser assertions passed\n";
}
