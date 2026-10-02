#!/system/bin/sh
# Development skeleton only. No daemon, cgroup/sysfs/property writes or boot waits.
# customize.sh intentionally rejects installation until a device adapter is validated.
MODDIR=${0%/*}
[ -f "$MODDIR/disable" ] && exit 0
printf '%s\n' 'Guizang: development-only, disabled; no device executor bundled.'
exit 0
