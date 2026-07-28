#!/bin/sh
# Report and optionally truncate oversized Docker container logs.
#
# Log rotation (max-size/max-file) is configured in docker-compose.yml and
# docker-compose.monitoring.yml via the shared `x-logging` anchor. That only
# governs *new* log growth, though: containers already carrying a bloated
# log file keep it until they're recreated. Run this script to reclaim disk
# space from existing containers without a restart.
#
# Usage:
#   ./trim_docker_logs.sh          # just report sizes
#   ./trim_docker_logs.sh --trim   # also truncate every log to 0 bytes

set -eu

TRIM="${1:-}"

echo "Container log sizes:"
echo

docker ps -a --format '{{.Names}}' | while IFS= read -r name; do
    log_path=$(docker inspect --format '{{.LogPath}}' "$name" 2>/dev/null || true)
    if [ -z "$log_path" ] || [ ! -f "$log_path" ]; then
        continue
    fi
    size=$(du -h "$log_path" | cut -f1)
    printf '  %-30s %8s  %s\n' "$name" "$size" "$log_path"

    if [ "$TRIM" = "--trim" ]; then
        sudo truncate -s 0 "$log_path"
        echo "    -> truncated"
    fi
done

echo
if [ "$TRIM" != "--trim" ]; then
    echo "Dry run only. Re-run with --trim to truncate all logs to 0 bytes."
fi
