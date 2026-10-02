#!/system/bin/sh
# Read-only capability hints, not a claim that safe app freezing is available.
printf 'schema=1\nmode=observe\nexecutor=unavailable\n'
if command -v getprop >/dev/null 2>&1; then
  printf 'android_sdk=%s\n' "$(getprop ro.build.version.sdk)"
  printf 'model=%s\n' "$(getprop ro.product.model)"
  printf 'soc=%s\n' "$(getprop ro.soc.model)"
else
  printf 'android_sdk=unknown\nmodel=host\nsoc=unknown\n'
fi
if [ -r /sys/fs/cgroup/cgroup.controllers ]; then
  printf 'cgroup_v2=observed\n'
else
  printf 'cgroup_v2=unknown\n'
fi
# cgroup.freeze is a core interface: absence from cgroup.controllers is NOT rejection.
printf 'binder_coordinator=unverified\nframework_lifecycle=unverified\nverified_thaw=false\n'
printf 'protection_signals=unknown\nfreezing=disabled\nperformance_writes=disabled\n'
