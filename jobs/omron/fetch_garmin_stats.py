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
    if not os.path.exists(CONFIG_PATH): return
    try:
        with open(CONFIG_PATH, "r") as f:
            conf = json.load(f)

        # FIX: Wymuszamy domain przed login() → garth NIE odpytuje api.ipify.org
        # Bez tego garth robi burst DNS A+AAAA przy każdym wywołaniu skryptu
        garth.configure(domain="garmin.com")

        with open(f"{BASE_PATH}/user/{conf['omron']['email']}", 'r') as tf:
            client = Garmin()
            client.login(tf.read())
        
        today = date.today().isoformat()
        stats = client.get_stats(today) or {}
        sleep = client.get_sleep_data(today) or {}
        dto = sleep.get('dailySleepDTO', {})

        # 1. Wynik snu
        ss = dto.get('sleepScore') 
        if not ss:
            ss = dto.get('sleepScores', {}).get('overall', {}).get('value', 0)
        
        # 2. Czas snu
        s_start = dto.get('sleepStartTimestampGMT', 0)
        s_end = dto.get('sleepEndTimestampGMT', 0)
        sh_sec = dto.get('totalSleepSeconds') or ((s_end - s_start) / 1000 if s_end > 0 else 0)
        sh = round(float(sh_sec) / 3600, 1)

        # 3. Parametry dodatkowe
        stress = stats.get('averageStressLevel', "0")
        bb = stats.get('bodyBatteryMostRecentValue', "0")
        rhr = stats.get('restingHeartRate') or sleep.get('restingHeartRate', "0")

        # 4. Czas synchronizacji (Lokalny)
        raw_ls = stats.get('lastSyncTimestampGMT', "")
        last_sync = datetime.fromisoformat(raw_ls.replace(" ","T")).replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S") if raw_ls else ""

        print(f"SUKCES: Złapano {ss} pkt snu ({sh}h). Sync: {last_sync}")

    except Exception as e:
        print(f"BŁĄD: {e}"); sys.exit(1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res = {"ts": int(time.time()), "time": now, "stress": stress, "bb": bb, "rhr": rhr, "sleep_score": ss, "sleep_hours": sh, "message": f"Sync: {last_sync}"}
    
    with open(JSON_FILE, "w", encoding="utf-8") as f: json.dump(res, f, indent=2)

    # Zapis do CSV (Force update dla punktacji)
    try:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip()]
            last_line = lines[-1].split(';')
            last_csv_sync, last_csv_ss = last_line[7].strip(), int(last_line[5] or 0)
    except: last_csv_sync, last_csv_ss = "", 0

    if last_sync == last_csv_sync and ss > last_csv_ss:
        lines[-1] = f"{res['ts']};{now};{stress};{bb};{rhr};{ss};{sh};{last_sync}\n"
        with open(CSV_FILE, "w", encoding="utf-8") as f: f.writelines(lines)
        print("AKTUALIZACJA: Wynik snu w CSV został poprawiony.")
    elif last_sync != last_csv_sync:
        with open(CSV_FILE, "a", encoding="utf-8") as f:
            f.write(f"{res['ts']};{now};{stress};{bb};{rhr};{ss};{sh};{last_sync}\n")
        print("SUKCES: Dodano nowy wpis do CSV.")
    else:
        print(f"INFO: Dane w CSV są już aktualne ({ss} pkt).")

if __name__ == "__main__": main()