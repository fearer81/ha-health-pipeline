#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pobiera kroki z Garmina (fetch_garmin_steps.py) i publikuje do MQTT."""

import os
import csv
import json
import time
import subprocess
import paho.mqtt.client as mqtt

# ===== CONFIG =====
CSV_PATH = os.getenv("KROKI_CSV", "/root/ha-project/external/export2garmin/user/kroki.csv")

VENV_PY = "/root/ha-project/external/export2garmin/venv/bin/python"
FETCH_JOB = "/root/ha-project/jobs/garmin/fetch_garmin_steps.py"

MQTT_SERVER = os.getenv("MQTT_HOST", "192.168.1.41")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "fear")
MQTT_PASS = os.getenv("MQTT_PASS")

HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "400"))
REFRESH = int(os.getenv("REFRESH", "300"))
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", "10800"))

HEALTH_FILE = "/root/ha-project/health/kroki_mqtt.json"

DEV = {
    "identifiers": ["garmin_kroki"],
    "name": "Garmin Kroki",
    "manufacturer": "Garmin",
    "model": "Connect API",
}

SENSORY = [
    ("kroki_dzis", "Dziś", "kroki", "mdi:walk", None, "measurement"),
    ("kroki_z_aktywnosci_dzis", "Z aktywności dziś", "kroki", "mdi:run", None, "measurement"),
    ("dystans_dzis", "Dystans dziś", "km", "mdi:map-marker-distance", "distance", "measurement"),
    ("czas_aktywnosci_dzis", "Czas aktywności dziś", None, "mdi:timer-outline", None, None),
]


def run_fetch():
    try:
        p = subprocess.run([VENV_PY, FETCH_JOB], capture_output=True,
                           text=True, timeout=180)
        for ln in (p.stdout or "").splitlines():
            print(f"[FETCH] {ln}")
        if p.returncode != 0:
            print(f"[FETCH] kod {p.returncode} — publikuję z istniejącego CSV")
            for ln in (p.stderr or "").splitlines()[-5:]:
                print(f"[FETCH] {ln}")
        return p.returncode == 0
    except subprocess.TimeoutExpired:
        print("[FETCH] timeout 180s")
        return False
    except Exception as e:
        print(f"[FETCH] error: {e}")
        return False


def update_health(rows, published):
    try:
        now = int(time.time())
        last = rows[0] if rows else None
        age_sec = now - int(last["ts"]) if last else 0

        if not rows:
            status = "DEAD"
        elif age_sec < 26 * 3600:
            status = "OK"
        elif age_sec < 3 * 24 * 3600:
            status = "WARNING"
        else:
            status = "DEAD"

        data = {
            "ts": now,
            "time": time.strftime("%d.%m %H:%M", time.localtime(now)),
            "age_sec": age_sec,
            "age_h": round(age_sec / 3600, 1),
            "status": status,
            "dni": len(rows),
            "published": published,
        }
        if last:
            data["ostatni_dzien"] = last["data"]
            data["kroki"] = last["kroki"]

        os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
        tmp = HEALTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, HEALTH_FILE)
    except Exception as e:
        print(f"[HEALTH] write error: {e}")


def safe_int(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def safe_float(x):
    try:
        return round(float(x), 2)
    except Exception:
        return 0.0


def get_rows():
    if not os.path.exists(CSV_PATH):
        print(f"[CSV] Brak pliku: {CSV_PATH}")
        return []

    rows = []
    try:
        with open(CSV_PATH, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                data = (r.get("Date") or "").strip()
                if not data:
                    continue

                kroki = safe_int(r.get("Daily Steps"))
                akt = safe_int(r.get("Activity Steps"))
                dyst_dz = safe_float(r.get("Daily Distance [km]"))
                dyst_akt = safe_float(r.get("Distance [km]"))

                rows.append({
                    "ts": safe_int(r.get("Unix Time")),
                    "data": data,
                    "kroki": kroki,
                    "aktywnosci": akt,
                    "poza": max(0, kroki - akt),
                    "dystans_dzienny": dyst_dz,
                    "dystans": dyst_akt,
                    "poza_km": round(max(0.0, dyst_dz - dyst_akt), 2),
                    "swim_km": safe_float(r.get("Swim Distance [km]")),
                    "swim_dlugosci": safe_int(r.get("Swim Lengths")),
                    "czas": (r.get("Duration [hh:mm:ss]") or "00:00:00").strip(),
                    "aktualizacja": (r.get("Last Update") or "").strip(),
                })
    except Exception as e:
        print(f"[CSV] read error: {e}")
        return []

    rows.sort(key=lambda x: x["data"], reverse=True)
    return rows[:HISTORY_SIZE]


def publish_discovery(client):
    client.publish(
        "homeassistant/sensor/kroki_history/config",
        json.dumps({
            "name": "Historia",
            "has_entity_name": True,
            "unique_id": "kroki_historia_v2",
            "state_topic": "homeassistant/sensor/kroki_history/state",
            "json_attributes_topic": "homeassistant/sensor/kroki_history/attributes",
            "icon": "mdi:table",
            "device": DEV,
        }),
        retain=True,
    )

    for key, name, unit, icon, dev_class, state_class in SENSORY:
        cfg = {
            "name": name,
            "has_entity_name": True,
            "unique_id": f"{key}_v2",
            "state_topic": f"homeassistant/sensor/{key}/state",
            "icon": icon,
            "device": DEV,
        }
        if unit:
            cfg["unit_of_measurement"] = unit
        if dev_class:
            cfg["device_class"] = dev_class
        if state_class:
            cfg["state_class"] = state_class

        client.publish(f"homeassistant/sensor/{key}/config",
                       json.dumps(cfg), retain=True)

    print("[MQTT] discovery opublikowane")


def publish_data(client, rows):
    last = rows[0]

    client.publish("homeassistant/sensor/kroki_history/state",
                   last["data"], retain=True)
    info = client.publish(
        "homeassistant/sensor/kroki_history/attributes",
        json.dumps({"rows": rows, "dni": len(rows)}, ensure_ascii=False),
        retain=True,
    )
    info.wait_for_publish()

    for key, val in (
        ("kroki_dzis", max(last["kroki"], last["aktywnosci"])),
        ("kroki_z_aktywnosci_dzis", last["aktywnosci"]),
        ("dystans_dzis", max(last["dystans_dzienny"], last["dystans"])),
        ("czas_aktywnosci_dzis", last["czas"]),
    ):
        client.publish(f"homeassistant/sensor/{key}/state", val, retain=True)

    print(f"[MQTT] {len(rows)} dni | {last['data']}: {last['kroki']} kroków "
          f"({last['aktywnosci']} z aktywności) | "
          f"{last['dystans_dzienny']} km dz. / {last['dystans']} km akt. | {last['czas']}")


def main():
    client = mqtt.Client()
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    while True:
        try:
            client.connect(MQTT_SERVER, MQTT_PORT, 60)
            break
        except Exception as e:
            print(f"[MQTT] connect failed ({e}) — retry za 30s")
            time.sleep(30)

    client.loop_start()
    publish_discovery(client)

    ostatni_hash = None
    ostatni_fetch = 0

    while True:
        try:
            if time.time() - ostatni_fetch >= FETCH_INTERVAL:
                run_fetch()
                ostatni_fetch = time.time()

            rows = get_rows()
            if not rows:
                update_health([], False)
                time.sleep(REFRESH)
                continue

            h = hash(json.dumps(rows, sort_keys=True))
            if h != ostatni_hash:
                publish_data(client, rows)
                ostatni_hash = h
                update_health(rows, True)
            else:
                update_health(rows, False)

        except Exception as e:
            print(f"[LOOP] error: {e}")

        time.sleep(REFRESH)


if __name__ == "__main__":
    main()
