#!/usr/bin/env python3
import os, time, sys, json, csv
import garth
from datetime import datetime, date, timezone
from garminconnect import Garmin

# --- KONFIGURACJA ---
BASE_PATH = "/root/ha-project/external/export2garmin"
CSV_FILE = f"{BASE_PATH}/user/garmin_stats.csv"
JSON_FILE = "/root/ha-project/health/garmin.json"
CONFIG_PATH = "/root/.config/omramin/config.json"

def main():
    if not os.path.exists(CONFIG_PATH): 
        print("BŁĄD: Brak pliku konfiguracyjnego."); return
    
    try:
        with open(CONFIG_PATH, "r") as f:
            conf = json.load(f)

        # FIX: Wymuszamy domain przed login()
        garth.configure(domain="garmin.com")

        token_path = f"{BASE_PATH}/user/{conf['omron']['email']}"
        if not os.path.exists(token_path):
            print(f"BŁĄD: Brak tokena w {token_path}"); return

        with open(token_path, 'r') as tf:
            client = Garmin()
            client.login(tf.read())
        
        today = date.today().isoformat()
        stats = client.get_stats(today) or {}
        sleep = client.get_sleep_data(today) or {}
        dto = sleep.get('dailySleepDTO') or {}

        # --- BEZPIECZNE POBIERANIE DANYCH (obsługa null/None) ---
        
        # 1. Wynik snu (jeśli null -> 0)
        ss = dto.get('sleepScore')
        if ss is None:
            ss = dto.get('sleepScores', {}).get('overall', {}).get('value')
        ss = int(ss) if ss is not None else 0
        
        # 2. Czas snu
        s_start = dto.get('sleepStartTimestampGMT') or 0
        s_end = dto.get('sleepEndTimestampGMT') or 0
        
        # Obliczamy czas trwania (totalSleepSeconds może być null)
        sh_sec = dto.get('totalSleepSeconds')
        if sh_sec is None:
            sh_sec = (s_end - s_start) / 1000 if (s_end and s_start) else 0
        
        sh = round(float(sh_sec) / 3600, 1)

        # 3. Parametry dodatkowe (jeśli null -> "0")
        stress = stats.get('averageStressLevel') or "0"
        bb = stats.get('bodyBatteryMostRecentValue') or "0"
        rhr = stats.get('restingHeartRate') or sleep.get('restingHeartRate') or "0"

        # 4. Czas synchronizacji
        raw_ls = stats.get('lastSyncTimestampGMT', "")
        last_sync = ""
        if raw_ls:
            try:
                last_sync = datetime.fromisoformat(raw_ls.replace(" ","T")).replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
            except:
                last_sync = ""

        print(f"INFO: Wynik snu: {ss} pkt, Czas: {sh}h. Sync: {last_sync or 'Brak'}")

    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {e}")
        sys.exit(1)

# Przygotowanie wyniku - KLUCZE MUSZĄ SIĘ ZGADZAĆ Z DASHBOARDEM
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# Przygotowanie wyniku z kluczami, których szuka Dashboard
    res = {
        "ts": int(time.time()),
        "stress": stress,
        "bb": bb,
        "rhr": rhr,
        "ss": ss,   # Zmienione z sleep_score na ss
        "sh": sh,   # Zmienione z sleep_hours na sh
        "ls": last_sync,     # Zmienione z time na ls (musi zawierać datę z 'T', np. 2026-04-18T23:06:41)
        "message": f"Sync: {last_sync}"
    }
    
    # Zapis do JSON (dla MQTT)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    # --- ZAPIS DO CSV (z zabezpieczeniem przed None) ---
    lines = []
    last_csv_sync = ""
    last_csv_ss = 0

    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                lines = [l for l in f.readlines() if l.strip()]
                if lines:
                    last_line = lines[-1].split(';')
                    last_csv_sync = last_line[7].strip() if len(last_line) > 7 else ""
                    last_csv_ss = int(last_line[5]) if last_line[5].isdigit() else 0
        except Exception as e:
            print(f"Ostrzeżenie przy odczycie CSV: {e}")

    # Logika aktualizacji: jeśli ta sama synchronizacja, ale wynik snu wzrósł (Garmin przeliczył)
    new_line = f"{res['ts']};{now};{stress};{bb};{rhr};{ss};{sh};{last_sync}\n"

    if last_sync and last_sync == last_csv_sync:
        if ss > last_csv_ss:
            lines[-1] = new_line
            with open(CSV_FILE, "w", encoding="utf-8") as f: f.writelines(lines)
            print("AKTUALIZACJA: Poprawiono wynik snu w istniejącym wpisie CSV.")
        else:
            print("INFO: Dane w CSV są już aktualne.")
    else:
        # Dodaj nowy wpis tylko jeśli last_sync nie jest pusty (mamy nową porcję danych)
        with open(CSV_FILE, "a", encoding="utf-8") as f:
            f.write(new_line)
        print("SUKCES: Dodano nowe dane do CSV.")

if __name__ == "__main__":
    main()