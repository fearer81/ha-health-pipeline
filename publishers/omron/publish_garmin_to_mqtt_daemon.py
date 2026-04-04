#!/usr/bin/env python3
import os, json, time, sys, paho.mqtt.client as mqtt

# --- KONFIGURACJA ŚCIEŻEK ---
CSV_FILE = "/root/ha-project/external/export2garmin/user/garmin_stats.csv"
ENV_FILE = "/etc/default/miscale-mqtt"

TOPIC_HISTORY = "hubert/garmin_stats/history"
TOPIC_LATEST = "hubert/garmin_stats/latest"

def load_env_file(path):
    """Wczytuje hasła z /etc/default/miscale-mqtt jeśli nie ma ich w systemie."""
    if not os.path.exists(path): return
    with open(path, 'r') as f:
        for line in f:
            if not line.startswith('#') and '=' in line:
                key, value = line.strip().split('=', 1)
                if key.startswith('MQTT_'):
                    os.environ[key] = value.strip('"').strip("'")

def main():
    # 1. Ładowanie haseł (z pliku /etc/default/miscale-mqtt)
    load_env_file(ENV_FILE)
    
    server = os.getenv("MQTT_HOST", "192.168.1.41")
    user = os.getenv("MQTT_USER", "fear")
    password = os.getenv("MQTT_PASS")

    if not password:
        print(f"BŁĄD: Nie znaleziono hasła MQTT w {ENV_FILE}")
        sys.exit(1)

    # 2. Konfiguracja Klienta MQTT
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(user, password)
    
    try: 
        client.connect(server, 1883, 60)
        client.loop_start()
        print(f"[OK] Połączono z MQTT ({server}) jako {user}")
    except Exception as e:
        print(f"[FATAL] Błąd połączenia MQTT: {e}")
        return

    last_mtime = 0

    while True:
        if os.path.exists(CSV_FILE):
            try:
                current_mtime = os.path.getmtime(CSV_FILE)
                if current_mtime != last_mtime:
                    with open(CSV_FILE, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        if len(lines) > 1:
                            rows = []
                            for l in lines[1:]:
                                p = l.strip().split(';')
                                if len(p) >= 8:
                                    rows.append({
                                        "ts": int(p[0]), "time": p[1], "stress": p[2],
                                        "bb": p[3], "rhr": p[4], "ss": p[5], "sh": p[6], "ls": p[7]
                                    })
                            rows.sort(key=lambda x: x['ts'], reverse=True)
                            
                            client.publish(TOPIC_HISTORY, json.dumps({"rows": rows[:200]}), retain=True)
                            
                            if rows:
                                latest = rows[0]
                                client.publish(TOPIC_LATEST, json.dumps({
                                    "sync": latest['ls'],
                                    "stress": latest['stress'],
                                    "bb": latest['bb'],
                                    "rhr": latest['rhr'],
                                    "sleep_score": latest['ss'],
                                    "sleep_hours": latest['sh']
                                }), retain=True)
                                print(f"[DATA] Wysłano aktualizację Garmin: {latest['ls']}")
                    
                    last_mtime = current_mtime
            except Exception as e: 
                print(f"Błąd: {e}")
        time.sleep(10)

if __name__ == "__main__": main()
