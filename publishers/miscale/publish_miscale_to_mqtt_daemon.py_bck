#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, csv, json, time, sys, paho.mqtt.client as mqtt

# ===== CONFIG =====
MQTT_HOST = os.getenv("MQTT_HOST", "192.168.1.41")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "fear")
MQTT_PASS = os.getenv("MQTT_PASS")

TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "hubert/scale_s400")
STATE_TOPIC = f"{TOPIC_PREFIX}/state"
HISTORY_TOPIC = f"{TOPIC_PREFIX}/history"

CSV_FILE = os.getenv("CSV_FILE", "/root/ha-project/external/export2garmin/user/miscale_backup.csv")
HEALTH_FILE = "/root/ha-project/health/miscale.json"
TARGET_WEIGHT = float(os.getenv("TARGET_WEIGHT", "85"))

def _to_float(x):
    try: return float(str(x).replace(",", "."))
    except: return None

def _parse_fat_to_ideal(x):
    """'to_lose:11.9' / 'to_gain:2.3' -> 11.9 / -2.3"""
    if not x:
        return None
    s = str(x).strip()
    try:
        if ":" in s:
            kind, val = s.split(":", 1)
            v = _to_float(val)
            if v is None:
                return None
            return -v if "gain" in kind.lower() else v
        return _to_float(s)
    except Exception:
        return None

def format_history_row(p):
    """Formatowanie pod Twoją kartę YAML (musi mieć wszystkie klucze!)."""
    return {
        "ts": p["ts"],
        "time": time.strftime("%d.%m %H:%M", time.localtime(p["ts"])),
        "weight": f"{p['weight']:.1f} kg" if p["weight"] is not None else "0.0 kg",
        "fat_to_ideal": f"{max(0, round(p['weight'] - TARGET_WEIGHT, 1)):.1f} kg" if p["weight"] else "0.0 kg",
        "change": f"{p['change']:.1f} kg" if p["change"] is not None else "0.0 kg",
        "bmi": f"{p['bmi']:.1f}" if p["bmi"] else "0.0",
        "body_fat": f"{p['body_fat']:.1f} %" if p["body_fat"] else "0.0 %",
        "body_water": f"{p['body_water']:.1f} %" if p["body_water"] else "0.0 %",
        "visceral_fat": f"{p['visceral_fat']:.1f}" if p["visceral_fat"] else "0.0",
        "bmr": f"{p['bmr']:.1f} kcal" if p["bmr"] else "0 kcal",
        "metabolic_age": f"{p['metabolic_age']:.1f} y" if p["metabolic_age"] else "0 y"
    }

def format_state_row(p):
    """Liczby pod sensory."""
    tluszcz_do_idealu = round(max(0, p["weight"] - TARGET_WEIGHT), 1) if p["weight"] else 0
    return {
        "ts": p["ts"],
        "time": time.strftime("%d.%m %H:%M", time.localtime(p["ts"])),
        "state": "OK",
        "weight": p["weight"],
        "heart_rate": p["heart_rate"],
        "bmi": p["bmi"],
        "body_fat": p["body_fat"],
        "body_water": p["body_water"],
        "visceral_fat": p["visceral_fat"],
        "bmr": p["bmr"],
        "metabolic_age": p["metabolic_age"],
        "muscle_mass": p["muscle_mass"],
        "bone_mass": p["bone_mass"],
        "bialko": p["protein"],
        "skeletal_muscle_mass": p["skeletal_muscle"],
        "physique_rating": p["physique_rating"],
        "zmiana": p["change"],
        "tluszcz_do_idealu": tluszcz_do_idealu,
        # Aliasy angielskie - konfiguracje encji MQTT odwolują się do tych nazw
        "protein": p["protein"],
        "weight_change": p["change"],
        # Wartości własne wagi (nie liczone z TARGET_WEIGHT)
        "lbm": p["lbm"],
        "ideal_weight": p["ideal_weight"],
        "fat_mass_to_ideal": p["fat_mass_to_ideal"],
        "impedance": p["impedance"],
        "impedance_low": p["impedance_low"],
        "note": "OK"
    }

def parse_row(r):
    ts = int(float(r.get("Unix Time") or time.time()))
    return {
        "ts": ts,
        "weight": _to_float(r.get("Weight [kg]")),
        "heart_rate": _to_float(r.get("Heart Rate [bpm]")) or _to_float(r.get("Heart Rate")),
        "bmi": _to_float(r.get("BMI")),
        "body_fat": _to_float(r.get("Body Fat [%]")),
        "body_water": _to_float(r.get("Body Water [%]")),
        "visceral_fat": _to_float(r.get("Visceral Fat")),
        "bmr": _to_float(r.get("BMR [kCal]")),
        "metabolic_age": _to_float(r.get("Metabolic Age [years]")),
        "muscle_mass": _to_float(r.get("Muscle Mass [kg]")),
        "bone_mass": _to_float(r.get("Bone Mass [kg]")),
        "protein": _to_float(r.get("Protein [%]")),
        "skeletal_muscle": _to_float(r.get("Skeletal Muscle Mass [kg]"))
                           or _to_float(r.get("Skeletal Muscle Mass [%]")),
        "physique_rating": _to_float(r.get("Physique Rating")),
        "change": _to_float(r.get("Change [kg]")),
        # UWAGA: "Ideal Wieght" - literówka jest w oryginalnym nagłówku CSV
        "lbm": _to_float(r.get("LBM [kg]")),
        "ideal_weight": _to_float(r.get("Ideal Wieght [kg]")) or _to_float(r.get("Ideal Weight [kg]")),
        "fat_mass_to_ideal": _parse_fat_to_ideal(r.get("Fat Mass To Ideal [type:mass kg]")),
        "impedance": _to_float(r.get("Impedance")),
        "impedance_low": _to_float(r.get("Impedance Low"))
    }

def connect_mqtt():
    """Łączy z brokerem, ponawia w nieskończoność zamiast ubijać demona."""
    while True:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            if MQTT_USER and MQTT_PASS:
                client.username_pw_set(MQTT_USER, MQTT_PASS)
            client.connect(MQTT_HOST, MQTT_PORT, 60)
            client.loop_start()
            print("[MQTT] Połączono", flush=True)
            return client
        except Exception as e:
            print(f"[MQTT] Connect error: {e} - ponowna próba za 30s", flush=True)
            time.sleep(30)

def main():
    client = connect_mqtt()

    last_ts = 0
    last_history_payload = None

    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)

    while True:
        if os.path.exists(CSV_FILE):
            try:
                with open(CSV_FILE, encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter=";")
                    rows = list(reader)
                
                if rows:
                    parsed_rows = []
                    for r in rows:
                        p = parse_row(r)
                        if p["weight"]: parsed_rows.append(p)
                    
                    parsed_rows.sort(key=lambda x: x["ts"], reverse=True)
                    
                    if parsed_rows:
                        # 1. Historia (Wszystkie klucze dla YAML)
                        history = [format_history_row(p) for p in parsed_rows]
                        history_payload = json.dumps({"rows": history[:200]})
                        # Publikuj tylko przy realnej zmianie - bez tego retain
                        # leciałby co 10s i obciążał brokera oraz recorder HA
                        if history_payload != last_history_payload:
                            client.publish(HISTORY_TOPIC, history_payload, retain=True)
                            last_history_payload = history_payload
                        
                        # 2. Stan (Dla sensorów)
                        newest_raw = parsed_rows[0]
                        if newest_raw["ts"] > last_ts:
                            client.publish(STATE_TOPIC, json.dumps(format_state_row(newest_raw)), retain=True)
                            last_ts = newest_raw["ts"]
                            with open(HEALTH_FILE, "w") as hf:
                                now = int(time.time())
                                age_sec = now - newest_raw["ts"]
                                health = {
                                    "ts": now,
                                    "time": time.strftime("%d.%m %H:%M", time.localtime(now)),
                                    "age_sec": age_sec,
                                    "age_min": int(age_sec / 60),
                                    "status": "OK" if age_sec < 2 * 3600 else ("WARNING" if age_sec < 24 * 3600 else "DEAD"),
                                    "measured_at": time.strftime("%d.%m.%Y %H:%M", time.localtime(newest_raw["ts"])),
                                    "weight": newest_raw["weight"],
                                    "bmi": newest_raw["bmi"],
                                    "body_fat": newest_raw["body_fat"],
                                    "visceral_fat": newest_raw["visceral_fat"],
                                }
                                json.dump(health, hf, indent=2)
                                hf.write("\n")
            except Exception as e:
                print(f"Error: {e}", flush=True)
        time.sleep(10)

if __name__ == "__main__": main()