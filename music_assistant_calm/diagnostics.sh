#!/bin/sh
# Crash diagnostics for the add-on: log container memory use and OOM-kill counters
# every DIAG_INTERVAL seconds, then hand over to the upstream entrypoint.
#
# A process killed by the kernel (OOM) or by a native crash leaves no Python
# traceback, so the last few "[calm-diagnostics]" lines before a restart show whether
# memory was climbing, and PYTHONFAULTHANDLER (set in the Dockerfile) prints native
# stack traces for segfaults and aborts.
INTERVAL="${DIAG_INTERVAL:-15}"

read_file() { [ -r "$1" ] && tr '\n' ' ' < "$1" || printf 'n/a'; }

sample() {
    if [ -r /sys/fs/cgroup/memory.current ]; then
        # cgroup v2
        cur="$(read_file /sys/fs/cgroup/memory.current)"
        max="$(read_file /sys/fs/cgroup/memory.max)"
        events="$(read_file /sys/fs/cgroup/memory.events)"
    else
        # cgroup v1
        cur="$(read_file /sys/fs/cgroup/memory/memory.usage_in_bytes)"
        max="$(read_file /sys/fs/cgroup/memory/memory.limit_in_bytes)"
        events="$(read_file /sys/fs/cgroup/memory/memory.oom_control)"
    fi
    avail="$(awk '/MemAvailable/ {printf "%d", $2 / 1024}' /proc/meminfo 2>/dev/null)"
    rss="$(ps -eo rss,comm 2>/dev/null | awk '{s += $1} END {printf "%d", s / 1024}')"
    ffmpeg="$(pgrep -c ffmpeg 2>/dev/null || echo 0)"
    echo "[calm-diagnostics] cgroup_mem=${cur}B limit=${max} host_available=${avail:-?}MiB procs_rss=${rss:-?}MiB ffmpeg=${ffmpeg} events: ${events}"
}

(
    while true; do
        sample
        sleep "$INTERVAL"
    done
) &

exec /usr/local/bin/entrypoint.sh "$@"
