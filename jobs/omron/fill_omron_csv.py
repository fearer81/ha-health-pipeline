#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv, os, json, sys, time
from datetime import datetime, timedelta
import omramin
import omronconnect as OC

# ======= KONFIGURACJA =======
CSV_FILE = os.getenv("CSV_FILE", "/root/ha-project/external/export2garmin/user/omron_backup.csv")
CONFIG_PATH = "/root/.config/omramin/config.json"

def get_last_csv_ts():
    if not os.path.exists(CSV_FILE) or os.stat(CSV_FILE).st_size == 0: return 0
    try:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
            if not rows: return 0
            return int(float(rows[-1].get("Unix Time", 0)))
    except: return 0

def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"BŁĄD: Nie znaleziono {CONFIG_PATH}")
        return

    try:
        with open(CONFIG_PATH, "r") as f:
            config_data = json.load(f)
        
        # Logowanie z obsługą refresh tokena (biblioteka sama to robi)
        oc = omramin.omron_login(CONFIG_PATH)
        if not oc:
            print("BŁĄD: Nie udało się zalogować.")
            return

        # Pobieramy urządzenia z Twojego configu
        raw_devices = omramin.filter_devices(config_data['omron']['devices'])
        
        # Ustawiamy zakres: 30 dni wstecz w MILISEKUNDACH (wymagane dla API v2 EU)
        # To jest klucz do sukcesu w Polsce
        start_ms = int((datetime.now() - timedelta(days=3)).timestamp() * 1000)
        end_ms = int(datetime.now().timestamp() * 1000)

        all_measurements = []
        for dev_dict in raw_devices:
            # Tworzymy poprawny obiekt urządzenia klasy OmronDevice
            ocDev = OC.OmronDevice(**dev_dict)
            print(f"Pobieranie dla: {ocDev.name} (User {ocDev.user})...")
            
            # Pobieramy pomiary z parametrem milisekundowym
            m_list = oc.get_measurements(ocDev, searchDateFrom=start_ms, searchDateTo=end_ms)
            print(f"DEBUG: Chmura zwróciła {len(m_list)} pomiarów.")
            all_measurements.extend(m_list)

    except Exception as e:
        print(f"BŁĄD krytyczny: {e}")
        return

    last_ts = get_last_csv_ts()
    new_entries = []
    email = config_data['omron']['email']

    for m in all_measurements:
        # m.measurementDate jest już w milisekundach w bibliotece
        ts = int(m.measurementDate / 1000) 
        if ts > last_ts:
            new_entries.append({
                "Data Status": "uploaded",
                "Unix Time": ts,
                "Date [dd.mm.yyyy]": datetime.fromtimestamp(ts, tz=m.timeZone).strftime("%d.%m.%Y"),
                "Time [hh:mm]": datetime.fromtimestamp(ts, tz=m.timeZone).strftime("%H:%M"),
                "SYStolic [mmHg]": getattr(m, 'systolic', 0),
                "DIAstolic [mmHg]": getattr(m, 'diastolic', 0),
                "Heart Rate [bpm]": getattr(m, 'pulse', getattr(m, 'heart_rate', 0)),
                "Category": "Normal", "MOV": 0, "IHB": 0,
                "Email User": email,
                "Upload Date [dd.mm.yyyy]": datetime.now().strftime("%d.%m.%Y"),
                "Upload Time [hh:mm]": datetime.now().strftime("%H:%M"),
                "Difference Time [s]": 0
            })

    if new_entries:
        file_exists = os.path.isfile(CSV_FILE) and os.stat(CSV_FILE).st_size > 0
        fieldnames = ["Data Status", "Unix Time", "Date [dd.mm.yyyy]", "Time [hh:mm]", 
                      "SYStolic [mmHg]", "DIAstolic [mmHg]", "Heart Rate [bpm]", 
                      "Category", "MOV", "IHB", "Email User", 
                      "Upload Date [dd.mm.yyyy]", "Upload Time [hh:mm]", "Difference Time [s]"]
        
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, delimiter=";", fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for entry in sorted(new_entries, key=lambda x: x["Unix Time"]):
                writer.writerow(entry)
        print(f"SUKCES: Dodano {len(new_entries)} pomiarów.")
    else:
        print(f"CSV aktualny. Ostatni TS: {last_ts}. Chmura widzi łącznie: {len(all_measurements)}")

if __name__ == "__main__":
    main()