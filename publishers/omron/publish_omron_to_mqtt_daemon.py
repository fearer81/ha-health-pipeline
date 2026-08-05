#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import time
import os
from datetime import datetime
import paho.mqtt.client as mqtt


# ===== ENV FILE =====
# UWAGA: musi być wczytany PRZED definicją stałych poniżej,
# inaczej os.getenv() zwróci wartości domyślne zanim plik zostanie odczytany.
def _load_env_file(path="/etc/default/omron-mqtt"):
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))
    except Exception as e:
        print(f"[ENV] read error: {e}", flush=True)


_load_env_file()


# ===== CONFIG =====
CSV_PATH = os.getenv("CSV_FILE", "/root/ha-project/external/export2garmin/user/omron_backup.csv")
GARMIN_CSV = os.getenv("GARMIN_CSV", "/root/ha-project/external/export2garmin/user/garmin_stats.csv")

MQTT_SERVER = os.getenv("MQTT_HOST", "192.168.1.41")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "fear")
MQTT_PASS = os.getenv("MQTT_PASS")

MQTT_TOPIC = "homeassistant/sensor/omron_history/state"
MQTT_DISCOVERY_TOPIC = "homeassistant/sensor/omron_history/config"

# Temat dla sensorów pojedynczych (systolic / diastolic / heart_rate).
# Konfiguracje discovery tych encji już istnieją w brokerze i wskazują tutaj.
STATE_TOPIC = os.getenv("OMRON_STATE_TOPIC", "hubert/omron_m4/state")

HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "1000"))

# Okno czasowe sesji w sekundach (12 min = 10 min spec Omron M4 + 2 min margines)
# Omron: "Średnia z ostatnich 2 lub 3 odczytów dokonanych w odstępie 10 minut"
# 720s zamiast 600s — zabezpieczenie przed drobnym dryfem timestampów z chmury
SESSION_WINDOW = int(os.getenv("SESSION_WINDOW", "3600"))

HEALTH_FILE = "/root/ha-project/health/omron.json"


# ===== HEALTH =====
def update_health(entry=None):
    """entry = najnowsza PRAWDZIWA sesja Omron (n > 0), nie zaślepka Garmin."""
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


def parse_ls(ls_str):
    """'2026-04-17T09:11:23...' albo '2026-04-17 09:11:23' -> unix ts"""
    try:
        clean = ls_str.replace("T", " ").split(".")[0]
        return int(datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").timestamp())
    except Exception:
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
            # Wartości liczbowe — dla sensorów pojedynczych w HA
            "sys":      avg_sys,
            "dia":      avg_dia,
            "hr":       avg_hr,
        }

        if n > 1:
            # Dodaj zakres dla transparentności (np. "119-125/79-83")
            sys_vals = [r["_sys"] for r in session]
            dia_vals = [r["_dia"] for r in session]
            if max(sys_vals) != min(sys_vals) or max(dia_vals) != min(dia_vals):
                entry["pressure_range"] = f"{min(sys_vals)}-{max(sys_vals)}/{min(dia_vals)}-{max(dia_vals)}"

        aggregated.append(entry)

    return sorted(aggregated, key=lambda x: x["ts"], reverse=True)


# ===== ZAŚLEPKI GARMIN =====
def get_garmin_placeholder_rows(omron_rows):
    """
    Dla dni BEZ sesji Omron dodaje jeden syntetyczny wiersz (n=0),
    z ts = ostatnia synchronizacja Garmina danego dnia.
    Karta flex-table dopasowuje kolumny Garmin po czasie (pole 'ls'),
    więc zaślepka z trafionym ts wypełni je automatycznie.
    """
    if not os.path.exists(GARMIN_CSV):
        print(f"[GARMIN] Brak pliku: {GARMIN_CSV}")
        return []

    omron_days = {datetime.fromtimestamp(r["ts"]).date() for r in omron_rows}
    best_per_day = {}
    garmin_days = set()
    skipped = 0

    try:
        with open(GARMIN_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                # Preferuj Last Sync (po tym polu karta robi dopasowanie),
                # fallback na Unix Time. Odczyt po nazwie kolumny zamiast
                # po indeksie — odporny na zmianę układu CSV.
                ls_raw = None
                unix_raw = None
                for k, v in row.items():
                    if not k:
                        continue
                    key = k.strip().lower()
                    if "last sync" in key or "lastsync" in key:
                        ls_raw = v
                    elif "unix" in key:
                        unix_raw = v

                ts = parse_ls(ls_raw or "") or safe_int(unix_raw)
                if not ts:
                    skipped += 1
                    continue
                day = datetime.fromtimestamp(ts).date()
                garmin_days.add(day)
                if day in omron_days:
                    continue
                if day not in best_per_day or ts > best_per_day[day]:
                    best_per_day[day] = ts
    except Exception as e:
        print(f"[GARMIN] read error: {e}")
        return []

    print(f"[GARMIN] dni_omron={sorted(str(d) for d in omron_days)} "
          f"dni_garmin={sorted(str(d) for d in garmin_days)} "
          f"pominięte_wiersze={skipped} zaślepki={len(best_per_day)}")

    return [{
        "ts": ts,
        "time": datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M"),
        "pressure": "",
        "pulse": "",
        "n": 0,   # 0 = wiersz syntetyczny (tylko dane Garmin)
    } for ts in best_per_day.values()]


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
        merged_count = raw_total - sessions_total
        if merged_count > 0:
            print(f"[AGG] {raw_total} pomiarów → {sessions_total} sesji (połączono {merged_count})")

    placeholders = get_garmin_placeholder_rows(aggregated)

    merged = sorted(aggregated + placeholders, key=lambda x: x["ts"], reverse=True)
    return merged[:HISTORY_SIZE]


# ===== MQTT =====
def send_to_mqtt():
    client = None
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if MQTT_USER:
            client.username_pw_set(MQTT_USER, MQTT_PASS)

        client.connect(MQTT_SERVER, MQTT_PORT, 60)
        # loop_start() jest KONIECZNY — bez pętli sieciowej duży payload
        # nie zostanie wypchnięty przed disconnect()
        client.loop_start()

        rows = get_rows_from_csv()

        if not rows:
            print("[WARN] Brak danych do wysłania")
            return

        payload = json.dumps({"rows": rows})
        info = client.publish(MQTT_TOPIC, payload, retain=True)
        info.wait_for_publish(timeout=15)

        if not info.is_published():
            print("[MQTT] Publikacja historii nie potwierdzona w 15s")
            return

        # Health liczymy od najnowszej PRAWDZIWEJ sesji, nie od zaślepki
        first_real = next((r for r in rows if r.get("n", 0) > 0), None)
        update_health(first_real)

        # Sensory pojedyncze (systolic / diastolic / heart_rate) —
        # osobny temat, płaski JSON z liczbami
        if first_real:
            state_payload = json.dumps({
                "ts":         first_real["ts"],
                "time":       first_real["time"],
                "state":      "OK",
                "systolic":   first_real.get("sys"),
                "diastolic":  first_real.get("dia"),
                "heart_rate": first_real.get("hr"),
                "pressure":   first_real.get("pressure"),
                "n":          first_real.get("n"),
            })
            info2 = client.publish(STATE_TOPIC, state_payload, retain=True)
            info2.wait_for_publish(timeout=10)
            if not info2.is_published():
                print("[MQTT] Publikacja stanu nie potwierdzona w 10s")

        real_count = sum(1 for r in rows if r.get("n", 0) > 0)
        print(f"[OK] Wysłano {len(rows)} wierszy ({real_count} sesji + {len(rows) - real_count} zaślepek)")

    except Exception as e:
        print(f"[MQTT] Error: {e}")

    finally:
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass


# ===== MAIN =====
def main():
    last_mtime = (0, 0)

    print(f"[START] Omron MQTT publisher (SESSION_WINDOW={SESSION_WINDOW}s, garmin placeholders: ON)")

    while True:
        try:
            mt_omron  = os.path.getmtime(CSV_PATH)   if os.path.exists(CSV_PATH)   else 0
            mt_garmin = os.path.getmtime(GARMIN_CSV) if os.path.exists(GARMIN_CSV) else 0
            current_mtime = (mt_omron, mt_garmin)

            if current_mtime != last_mtime:
                send_to_mqtt()
                last_mtime = current_mtime
        except Exception as e:
            print(f"[LOOP] Error: {e}")

        time.sleep(10)


if __name__ == "__main__":
    main()