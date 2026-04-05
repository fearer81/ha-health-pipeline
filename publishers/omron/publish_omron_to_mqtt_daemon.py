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

# Okno czasowe sesji w sekundach (10 min — zgodnie ze specyfikacją Omron M4:
# "Średnia z ostatnich 2 lub 3 odczytów dokonanych w odstępie 10 minut")
SESSION_WINDOW = int(os.getenv("SESSION_WINDOW", "600"))

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

# ===== AGREGACJA SESJI =====
def aggregate_sessions(raw_rows, window=1800):
    """
    Grupuje pomiary w sesje — jeśli różnica czasu między pierwszym
    a kolejnym pomiarem w grupie <= window sekund, trafiają do tej samej sesji.

    Zwraca listę sesji ze uśrednionymi wartościami.
    Pole 'n' informuje z ilu pomiarów złożona jest sesja.
    Reprezentatywny timestamp i time = ostatni pomiar w sesji.
    """
    if not raw_rows:
        return []

    sorted_rows = sorted(raw_rows, key=lambda x: x["ts"])

    sessions = []
    current_session = [sorted_rows[0]]

    for row in sorted_rows[1:]:
        # Grupuj względem PIERWSZEGO pomiaru w sesji (nie poprzedniego)
        if row["ts"] - current_session[0]["ts"] <= window:
            current_session.append(row)
        else:
            sessions.append(current_session)
            current_session = [row]
    sessions.append(current_session)

    aggregated = []
    for session in sessions:
        n = len(session)
        avg_sys = round(sum(r["_sys"] for r in session) / n)
        avg_dia = round(sum(r["_dia"] for r in session) / n)

        hr_vals = [r["_hr"] for r in session if r["_hr"] is not None]
        avg_hr = round(sum(hr_vals) / len(hr_vals)) if hr_vals else None

        # Reprezentant sesji = ostatni pomiar (najnowszy timestamp w grupie)
        last = session[-1]

        entry = {
            "ts":       last["ts"],
            "time":     last["time"],
            "pressure": f"{avg_sys}/{avg_dia} mmHg",
            "pulse":    f"{avg_hr} bpm" if avg_hr else "",
            "n":        n,          # liczba pomiarów w sesji
        }

        if n > 1:
            # Dodaj zakres dla transparentności (np. "119-125/79-83")
            sys_vals = [r["_sys"] for r in session]
            dia_vals = [r["_dia"] for r in session]
            if max(sys_vals) != min(sys_vals) or max(dia_vals) != min(dia_vals):
                entry["pressure_range"] = f"{min(sys_vals)}-{max(sys_vals)}/{min(dia_vals)}-{max(dia_vals)}"

        aggregated.append(entry)

    return sorted(aggregated, key=lambda x: x["ts"], reverse=True)


# ===== CSV =====
def get_rows_from_csv():
    if not os.path.exists(CSV_PATH):
        print("CSV not found")
        return []

    raw_rows = []

    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")

            for row in reader:
                date     = row.get("Date [dd.mm.yyyy]", "")
                time_str = row.get("Time [hh:mm]", "")

                ts = parse_datetime(date, time_str)
                if not ts:
                    continue

                sys_val = safe_int(row.get("SYStolic [mmHg]"))
                dia_val = safe_int(row.get("DIAstolic [mmHg]"))
                hr_val  = safe_int(row.get("Heart Rate [bpm]"))

                if not sys_val or not dia_val:
                    continue

                raw_rows.append({
                    "ts":   ts,
                    "time": f"{date} {time_str}",
                    "_sys": sys_val,
                    "_dia": dia_val,
                    "_hr":  hr_val,
                })

    except Exception as e:
        print(f"CSV Read Error: {e}")
        return []

    aggregated = aggregate_sessions(raw_rows, window=SESSION_WINDOW)

    if aggregated:
        sessions_total = len(aggregated)
        raw_total = len(raw_rows)
        merged = raw_total - sessions_total
        if merged > 0:
            print(f"[AGG] {raw_total} pomiarów → {sessions_total} sesji (połączono {merged})")

    return aggregated[:HISTORY_SIZE]


# ===== MQTT =====
def send_to_mqtt():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if MQTT_USER:
            client.username_pw_set(MQTT_USER, MQTT_PASS)

        client.connect(MQTT_SERVER, MQTT_PORT, 60)

        rows = get_rows_from_csv()

        if not rows:
            print("[WARN] Brak danych do wysłania")
            return

        payload = json.dumps({"rows": rows})
        client.publish(MQTT_TOPIC, payload, retain=True)

        update_health(rows[0] if rows else None)

        print(f"[OK] Wysłano {len(rows)} sesji na MQTT")
        client.disconnect()

    except Exception as e:
        print(f"[MQTT] Error: {e}")


# ===== MAIN =====
def main():
    env_file = "/etc/default/omron-mqtt"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))

    last_mtime = 0

    print(f"[START] Omron MQTT publisher (SESSION_WINDOW={SESSION_WINDOW}s)")

    while True:
        try:
            if os.path.exists(CSV_PATH):
                current_mtime = os.path.getmtime(CSV_PATH)
                if current_mtime != last_mtime:
                    send_to_mqtt()
                    last_mtime = current_mtime
        except Exception as e:
            print(f"[LOOP] Error: {e}")

        time.sleep(10)


if __name__ == "__main__":
    main()
