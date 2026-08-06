#!/usr/bin/env python3
import os, time, sys, json, csv
import garth
from datetime import datetime, date, timedelta, timezone
from garminconnect import Garmin

# --- KONFIGURACJA ---
BASE_PATH = "/root/ha-project/external/export2garmin"
CSV_FILE = f"{BASE_PATH}/user/garmin_stats.csv"
JSON_FILE = "/root/ha-project/health/garmin.json"
CONFIG_PATH = "/root/.config/omramin/config.json"

# Ile dni wstecz próbować naprawiać wiersze z zerowym snem (0 = tylko dziś)
BACKFILL_DAYS = 1


def read_sleep(client, day_iso):
    """Zwraca (ss, sh, rhr_ze_snu) dla podanej daty YYYY-MM-DD."""
    sleep = client.get_sleep_data(day_iso) or {}
    dto = sleep.get('dailySleepDTO') or {}

    # 1. Wynik snu (jeśli null -> 0)
    ss = dto.get('sleepScore')
    if ss is None:
        ss = (dto.get('sleepScores') or {}).get('overall', {}).get('value')
    ss = int(ss) if ss is not None else 0

    # 2. Czas snu
    s_start = dto.get('sleepStartTimestampGMT') or 0
    s_end = dto.get('sleepEndTimestampGMT') or 0
    sh_sec = dto.get('totalSleepSeconds')
    if sh_sec is None:
        sh_sec = (s_end - s_start) / 1000 if (s_end and s_start) else 0
    sh = round(float(sh_sec) / 3600, 1)

    return ss, sh, sleep.get('restingHeartRate')


def parse_row(line):
    """CSV: ts;datetime;stress;bb;rhr;ss;sh;ls"""
    p = line.rstrip("\n").split(';')
    return p if len(p) >= 8 else None


def row_sleep(p):
    ss = int(p[5]) if p[5].strip().lstrip('-').isdigit() else 0
    try:
        sh = float(p[6])
    except ValueError:
        sh = 0.0
    return ss, sh


def backfill_day(lines, day_prefix, ss, sh):
    """Uzupełnia sen we wszystkich wierszach z danego dnia.
    Nadpisuje tylko w górę - nigdy nie kasuje już poprawnych danych."""
    if ss <= 0 and sh <= 0:
        return 0
    fixed = 0
    for i, ln in enumerate(lines):
        p = parse_row(ln)
        if not p or not p[1].startswith(day_prefix):
            continue
        old_ss, old_sh = row_sleep(p)
        if ss > old_ss or sh > old_sh:
            p[5] = str(ss)
            p[6] = str(sh)
            lines[i] = ";".join(p) + "\n"
            fixed += 1
    return fixed


def day_needs_backfill(lines, day_prefix):
    """True jeśli w danym dniu jest choć jeden wiersz z zerowym snem."""
    for ln in lines:
        p = parse_row(ln)
        if p and p[1].startswith(day_prefix):
            ss, sh = row_sleep(p)
            if ss <= 0 and sh <= 0:
                return True
    return False


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
        ss, sh, rhr_sleep = read_sleep(client, today)

        # 3. Parametry dodatkowe (jeśli null -> "0")
        stress = stats.get('averageStressLevel') or "0"
        bb = stats.get('bodyBatteryMostRecentValue') or "0"
        rhr = stats.get('restingHeartRate') or rhr_sleep or "0"

        # 4. Czas synchronizacji
        raw_ls = stats.get('lastSyncTimestampGMT', "")
        last_sync = ""
        if raw_ls:
            try:
                last_sync = datetime.fromisoformat(raw_ls.replace(" ", "T")).replace(
                    tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                last_sync = ""

        print(f"INFO: Wynik snu: {ss} pkt, Czas: {sh}h. Sync: {last_sync or 'Brak'}")

    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {e}")
        sys.exit(1)

    # Przygotowanie wyniku - KLUCZE MUSZĄ SIĘ ZGADZAĆ Z DASHBOARDEM
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res = {
        "ts": int(time.time()),
        "stress": stress,
        "bb": bb,
        "rhr": rhr,
        "ss": ss,   # Zmienione z sleep_score na ss
        "sh": sh,   # Zmienione z sleep_hours na sh
        "ls": last_sync,     # Zmienione z time na ls (musi zawierać datę z 'T')
        "message": f"Sync: {last_sync}"
    }

    # Zapis do JSON (dla MQTT)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    # --- ZAPIS DO CSV ---
    lines = []
    last_csv_sync = ""
    last_csv_ss = 0

    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                lines = [l for l in f.readlines() if l.strip()]
            if lines:
                last_line = parse_row(lines[-1])
                if last_line:
                    last_csv_sync = last_line[7].strip()
                    last_csv_ss = row_sleep(last_line)[0]
        except Exception as e:
            print(f"Ostrzeżenie przy odczycie CSV: {e}")

    dirty = False

    # --- BACKFILL: naprawa porannych wpisów bez snu ---
    # Wiersz zapisany o 06:20 (zegarek nie zamknął jeszcze snu) dostaje
    # właściwe ss/sh, gdy tylko Garmin je policzy.
    fixed = backfill_day(lines, today, ss, sh)
    if fixed:
        dirty = True
        print(f"BACKFILL: Uzupełniono sen w {fixed} wierszu/ach z {today}.")

    # Dni wstecz - tylko jeśli faktycznie są tam dziury (oszczędzamy API)
    for d in range(1, BACKFILL_DAYS + 1):
        prev = (date.today() - timedelta(days=d)).isoformat()
        if not day_needs_backfill(lines, prev):
            continue
        try:
            p_ss, p_sh, _ = read_sleep(client, prev)
            fixed = backfill_day(lines, prev, p_ss, p_sh)
            if fixed:
                dirty = True
                print(f"BACKFILL: Uzupełniono sen w {fixed} wierszu/ach z {prev}.")
        except Exception as e:
            print(f"Ostrzeżenie przy backfill {prev}: {e}")

    # --- NOWY WIERSZ / AKTUALIZACJA ---
    new_line = f"{res['ts']};{now};{stress};{bb};{rhr};{ss};{sh};{last_sync}\n"

    if last_sync and last_sync == last_csv_sync:
        # Ta sama synchronizacja - aktualizujemy ostatni wiersz jeśli sen wzrósł
        if ss > last_csv_ss:
            lines[-1] = new_line
            dirty = True
            print("AKTUALIZACJA: Poprawiono wynik snu w istniejącym wpisie CSV.")
        else:
            print("INFO: Dane w CSV są już aktualne.")
    elif last_sync:
        # Nowa porcja danych (inny last_sync niż w ostatnim wierszu CSV) -> dopisz
        lines.append(new_line)
        dirty = True
        print("SUKCES: Dodano nowe dane do CSV.")
    else:
        # Brak last_sync = zegarek niezsynchronizowany / API nie zwróciło danych
        print("INFO: Brak last_sync (zegarek niezsynchronizowany) – pomijam zapis do CSV.")

    if dirty:
        tmp = CSV_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp, CSV_FILE)


if __name__ == "__main__":
    main()