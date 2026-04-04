#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import time
import os
from datetime import datetime
import paho.mqtt.client as mqtt

# ===== CONFIG =====
CSV_PATH = os.getenv("CSV_FILE", "/root/ha-project/external/export2garmin/user/omron_backup.csv")

MQTT_SERVER = os.getenv("MQTT_HOST", "192.168.1.41")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "fear")
MQTT_PASS = os.getenv("MQTT_PASS")

MQTT_TOPIC = "homeassistant/sensor/omron_history/state"
MQTT_DISCOVERY_TOPIC = "homeassistant/sensor/omron_history/config"

HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "100"))

HEALTH_FILE = "/root/ha-project/health/omron.json"

# ===== HEALTH =====
def update_health(entry=None):
    try:
        now = int(time.time())

        age_sec = 0
        if entry and entry.get("ts"):
            age_sec = now - int(entry["ts"])

        if age_sec < 2 * 3600:
            status = "OK"
        elif age_sec < 24 * 3600:
            status = "WARNING"
        else:
            status = "DEAD"

        data = {
            "ts": now,
            "time": time.strftime("%d.%m %H:%M", time.localtime(now)),
            "age_sec": age_sec,
            "age_min": int(age_sec / 60),
            "status": status
        }

        if entry:
            data["measured_at"] = entry.get("time")
            data["pressure"] = entry.get("pressure")

        os.makedirs("/root/ha-project/health", exist_ok=True)

        with open(HEALTH_FILE, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    except Exception as e:
        print(f"[HEALTH] write error: {e}")

# ===== HELPERS =====
def parse_datetime(date_str, time_str):
    try:
        return int(datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M").timestamp())
    except:
        return None

def safe_int(x):
    try:
        return int(float(x))
    except:
        return None

# ===== CSV =====
def get_rows_from_csv():
    if not os.path.exists(CSV_PATH):
        print("CSV not found")
        return []

    rows = {}

    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")

            for row in reader:
                date = row.get("Date [dd.mm.yyyy]", "")
                time_str = row.get("Time [hh:mm]", "")

                ts = parse_datetime(date, time_str)
                if not ts:
                    continue

                sys = safe_int(row.get("SYStolic [mmHg]"))
                dia = safe_int(row.get("DIAstolic [mmHg]"))
                hr  = safe_int(row.get("Heart Rate [bpm]"))

                if not sys or not dia:
                    continue

                rows[ts] = {
                    "ts": ts,
                    "time": f"{date} {time_str}",
                    "pressure": f"{sys}/{dia} mmHg",
                    "pulse": f"{hr} bpm" if hr else ""
                }

    except Exception as e:
        print(f"CSV Read Error: {e}")

    return sorted(rows.values(), key=lambda x: x["ts"], reverse=True)[:HISTORY_SIZE]

# ===== MQTT =====
def send_to_mqtt():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if MQTT_USER:
            client.username_pw_set(MQTT_USER, MQTT_PASS)

        client.connect(MQTT_SERVER, MQTT_PORT, 60)

        discovery_payload = {
            "name": "Omron M4 - Historia",
            "state_topic": MQTT_TOPIC,
            "value_template": "{{ value_json.state }}",
            "json_attributes_topic": MQTT_TOPIC,
            "icon": "mdi:table-clock",
            "unique_id": "omron_m4_history_fear81",
        }

        client.publish(MQTT_DISCOVERY_TOPIC, json.dumps(discovery_payload), retain=True)

        rows = get_rows_from_csv()

        client.publish(MQTT_TOPIC, json.dumps({
            "state": len(rows),
            "rows": rows
        }), retain=True)

        print(f"MQTT: Sent {len(rows)} records")

        if rows:
            update_health(rows[0])
        else:
            update_health()

        client.disconnect()

    except Exception as e:
        print(f"MQTT Error: {e}")

# ===== MAIN =====
if __name__ == "__main__":
    print(f"Starting Omron MQTT daemon → {CSV_PATH}")

    send_to_mqtt()

    last_mtime = os.path.getmtime(CSV_PATH) if os.path.exists(CSV_PATH) else 0

    while True:
        try:
            current_mtime = os.path.getmtime(CSV_PATH) if os.path.exists(CSV_PATH) else 0

            # health zawsze
            rows = get_rows_from_csv()
            if rows:
                update_health(rows[0])
            else:
                update_health()

            # publish tylko przy zmianie
            if current_mtime != last_mtime:
                print("CSV changed → publishing...")
                send_to_mqtt()
                last_mtime = current_mtime

        except Exception as e:
            print(f"Loop Error: {e}")

        time.sleep(10)