#!/bin/bash

VENV="/root/ha-project/external/export2garmin/venv/bin"
CONFIG="/root/ha-project/config/omramin/config.json" #symlink

while true; do
    echo "[$(date)] --- START CYKLU OMRON ---"

    if ! $VENV/omramin --config "$CONFIG" sync; then
        echo "FAIL → sleep 30 min"
        sleep 1800
        continue
    fi

    $VENV/python /root/ha-project/jobs/omron/fill_omron_csv.py
    $VENV/python /root/ha-project/jobs/omron/fetch_garmin_stats.py

    echo "[$(date)] Cykl zakończony. Czekam 5 min..."
    sleep 300
done