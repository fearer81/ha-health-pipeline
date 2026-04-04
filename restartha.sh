#!/usr/bin/env bash
# restartha — pełny pipeline restartu usług HA + export2garmin
set -euo pipefail

echo "=== daemon-reload ==="
systemctl daemon-reload

echo "=== czyszczę tmp ==="
rm -rf /root/ha-project/external/export2garmin/user/tmp/*

echo "=== restartuję usługi ==="
systemctl restart export2garmin garmin_monitor garmin-mqtt miscale-mqtt omron_sync omron-mqtt

echo ""
echo "=== STATUS ==="
for svc in export2garmin garmin_monitor garmin-mqtt miscale-mqtt omron_sync omron-mqtt; do
    echo "--- $svc ---"
    systemctl status "$svc" --no-pager -l
    echo ""
done

echo "=== health ==="
cat /root/ha-project/health/*
