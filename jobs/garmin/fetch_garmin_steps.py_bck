#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pobiera z Garmin Connect kroki dzienne + aktywności i zapisuje do CSV.

  user/kroki.csv     - jeden wiersz na dzień; nowe dni dopisywane,
                       istniejące aktualizowane (klucz = Date)
  health/kroki.json  - heartbeat (kiedy ostatnio, czy oba źródła odpowiedziały)

Zakres wyznaczany automatycznie z CSV (plik jest stanem, tak jak
w fetch_garmin_stats.py): od ostatniej daty minus OVERLAP_DAYS do dziś.

Kilka aktywności w jednym dniu jest sumowanych (kroki, dystans, czas).
Aktywność przypisywana jest do daty STARTU.
"""

import os
import sys
import csv
import json
import time
import argparse
from datetime import date, datetime, timedelta

import garth
from garminconnect import Garmin

# --- KONFIGURACJA ---
BASE_PATH = "/root/ha-project/external/export2garmin"
CONFIG_PATH = "/root/.config/omramin/config.json"

CSV_FILE = f"{BASE_PATH}/user/kroki.csv"
HEALTH_FILE = "/root/ha-project/health/kroki.json"

OVERLAP_DAYS = 3      # ile dni wstecz odświeżamy (Garmin dolicza kroki wstecz)
INITIAL_DAYS = 30     # ile pobrać przy pustym CSV

DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]

HDR = [
    "Unix Time", "Date", "Daily Steps", "Activity Steps",
    "Distance [km]", "Duration [hh:mm:ss]", "Last Update",
]


# ===== HELPERS =====
def pick(d, *names):
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


def hhmmss(sec):
    sec = int(round(sec or 0))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def day_ts(day_iso):
    return int(datetime.strptime(day_iso, "%Y-%m-%d").timestamp())


def atomic_write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)


def read_existing():
    if not os.path.exists(CSV_FILE):
        return {}
    try:
        with open(CSV_FILE, encoding="utf-8", newline="") as f:
            r = csv.reader(f, delimiter=";")
            hdr = next(r, None)
            if not hdr or "Date" not in hdr:
                print("[CSV] nieznany nagłówek — plik budowany od zera")
                return {}
            di = hdr.index("Date")
            return {row[di]: row for row in r if len(row) > di and row[di].strip()}
    except Exception as e:
        print(f"[CSV] błąd odczytu ({e}) — plik budowany od zera")
        return {}


def ustal_zakres(args, istniejace):
    end = args.end or date.today().isoformat()

    if args.start:
        return args.start, end, "ręczny (--start)"

    if args.days:
        return (date.today() - timedelta(days=args.days - 1)).isoformat(), end, \
               f"ręczny (--days {args.days})"

    if not istniejace:
        return (date.today() - timedelta(days=INITIAL_DAYS - 1)).isoformat(), end, \
               f"pierwsze uruchomienie ({INITIAL_DAYS} dni)"

    ostatni = max(istniejace)
    start_d = datetime.strptime(ostatni, "%Y-%m-%d").date() - timedelta(days=OVERLAP_DAYS)
    luka = (date.today() - datetime.strptime(ostatni, "%Y-%m-%d").date()).days
    return start_d.isoformat(), end, \
           f"auto (ostatni wpis {ostatni}, luka {luka} dni, zakładka {OVERLAP_DAYS})"


# ===== HEALTH =====
def update_health(status, zrodla, dni=0, ostatni_dzien=None, blad=None):
    try:
        now = int(time.time())
        data = {
            "ts": now,
            "time": time.strftime("%d.%m %H:%M", time.localtime(now)),
            "status": status,
            "zrodla": zrodla,
            "dni_w_csv": dni,
            "ostatni_dzien": ostatni_dzien,
        }
        if blad:
            data["blad"] = str(blad)[:300]

        os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
        tmp = HEALTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, HEALTH_FILE)
    except Exception as e:
        print(f"[HEALTH] write error: {e}")


# ===== LOGOWANIE =====
def login():
    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError("Brak pliku konfiguracyjnego.")

    with open(CONFIG_PATH, "r") as f:
        conf = json.load(f)

    garth.configure(domain="garmin.com")

    token_path = f"{BASE_PATH}/user/{conf['omron']['email']}"
    if not os.path.exists(token_path):
        raise RuntimeError(f"Brak tokena w {token_path}")

    with open(token_path, "r") as tf:
        client = Garmin()
        client.login(tf.read())

    return client


# ===== POBIERANIE =====
def fetch_daily(client, start, end):
    rows = client.get_daily_steps(start, end) or []
    out = {}
    for r in rows:
        day = pick(r, "calendarDate", "statisticsStartDate")
        if not day:
            continue
        out[day] = (
            int(pick(r, "totalSteps", "steps") or 0),
            int(pick(r, "stepGoal", "dailyStepGoal", "stepsGoal") or 0),
        )
    print(f"[API] get_daily_steps: {len(out)} dni")
    return out


def fetch_acts(client, start, end):
    acts = client.get_activities_by_date(start, end) or []
    print(f"[API] get_activities_by_date: {len(acts)} aktywności")

    out = {}
    for a in acts:
        st = pick(a, "startTimeLocal", "startTimeGMT") or ""
        if " " not in st:
            continue
        day = st.split(" ")[0]

        dyst_m = float(pick(a, "distance") or 0)
        czas_s = int(round(float(pick(a, "duration") or 0)))

        out.setdefault(day, []).append({
            "godzina": st.split(" ")[1][:5],
            "kroki": int(pick(a, "steps", "totalSteps") or 0),
            "dystans_km": round(dyst_m / 1000, 2),
            "czas_s": czas_s,
        })

    for day in out:
        out[day].sort(key=lambda x: x["godzina"])

    wiele = {d: len(v) for d, v in out.items() if len(v) > 1}
    if wiele:
        print(f"[AKT] dni z kilkoma aktywnościami: "
              f"{', '.join(f'{d} x{n}' for d, n in sorted(wiele.items()))}")
    return out


# ===== BUDOWA REKORDÓW =====
def build_days(daily, per_day):
    days = []
    for d in sorted(set(list(daily.keys()) + list(per_day.keys()))):
        acts = per_day.get(d, [])
        tot, cel = daily.get(d, (0, 0))

        suma_akt = sum(a["kroki"] for a in acts)
        czas_s = sum(a["czas_s"] for a in acts)
        roznica = tot - suma_akt

        days.append({
            "data": d,
            "dzien": DNI[datetime.strptime(d, "%Y-%m-%d").weekday()],
            "kroki_dzienne": tot,
            "cel": cel,
            "kroki_aktywnosci": suma_akt,
            "poza_aktywnosciami": max(0, roznica),
            "roznica": roznica,
            "rozbieznosc": roznica < 0,
            "liczba_aktywnosci": len(acts),
            "dystans_km": round(sum(a["dystans_km"] for a in acts), 2),
            "czas_s": czas_s,
            "czas": hhmmss(czas_s),
        })
    return days


def row_dzien(d, stamp):
    return [
        day_ts(d["data"]), d["data"],
        d["kroki_dzienne"], d["kroki_aktywnosci"],
        f"{d['dystans_km']:.2f}", d["czas"], stamp,
    ]


def merge(days, istniejace, stamp):
    idx = dict(istniejace)
    dopisane = zmienione = bez_zmian = 0

    for d in days:
        row = row_dzien(d, stamp)
        stary = idx.get(d["data"])
        if stary is None:
            idx[d["data"]] = row
            dopisane += 1
        elif [str(x) for x in stary[:-1]] != [str(x) for x in row[:-1]]:
            idx[d["data"]] = row
            zmienione += 1
        else:
            bez_zmian += 1

    rows = sorted(idx.values(), key=lambda r: r[1])
    print(f"[CSV] {len(rows)} dni w pliku "
          f"(dopisane: {dopisane}, zaktualizowane: {zmienione}, bez zmian: {bez_zmian})")
    return rows, dopisane + zmienione


# ===== RAPORT =====
def print_table(days):
    print("\n" + "=" * 88)
    print(f"{'Dzień':<14}{'Dzienne':>9}{'Aktywn.':>9}{'n':>3}{'Poza':>9}"
          f"{'Dyst.':>8}{'Czas':>11}{'Flaga':>14}")
    print("=" * 88)
    for d in days:
        flag = "ROZBIEŻNOŚĆ" if d["rozbieznosc"] else ""
        print(f"{d['data']} {d['dzien']:<4}"
              f"{d['kroki_dzienne']:>9,}{d['kroki_aktywnosci']:>9,}"
              f"{d['liczba_aktywnosci']:>3}{d['poza_aktywnosciami']:>9,}"
              f"{d['dystans_km']:>8.2f}{d['czas']:>11}{flag:>14}".replace(",", " "))
    print("-" * 88)
    print(f"{'RAZEM':<14}"
          f"{sum(d['kroki_dzienne'] for d in days):>9,}"
          f"{sum(d['kroki_aktywnosci'] for d in days):>9,}"
          f"{sum(d['liczba_aktywnosci'] for d in days):>3}"
          f"{sum(d['poza_aktywnosciami'] for d in days):>9,}"
          f"{sum(d['dystans_km'] for d in days):>8.2f}"
          f"{hhmmss(sum(d['czas_s'] for d in days)):>11}".replace(",", " "))
    print("=" * 88)


# ===== MAIN =====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    istniejace = read_existing()
    start, end, tryb = ustal_zakres(args, istniejace)
    print(f"[ZAKRES] {start} .. {end}  [{tryb}]")

    zrodla = {"daily_steps": False, "activities": False}

    try:
        client = login()
    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {e}")
        if not args.dry_run:
            update_health("ERROR", zrodla, dni=len(istniejace), blad=e)
        sys.exit(1)

    daily, per_day = {}, {}
    blad = None
    try:
        daily = fetch_daily(client, start, end)
        zrodla["daily_steps"] = True
    except Exception as e:
        blad = f"get_daily_steps: {e}"
        print(f"BŁĄD: {blad}")

    try:
        per_day = fetch_acts(client, start, end)
        zrodla["activities"] = True
    except Exception as e:
        blad = f"{blad + ' | ' if blad else ''}get_activities_by_date: {e}"
        print(f"BŁĄD: get_activities_by_date: {e}")

    if not all(zrodla.values()):
        print("Niekompletne dane z API — pomijam zapis CSV (stare wiersze nietknięte).")
        if not args.dry_run:
            update_health("ERROR", zrodla, dni=len(istniejace),
                          ostatni_dzien=max(istniejace) if istniejace else None, blad=blad)
        sys.exit(1)

    days = build_days(daily, per_day)
    if not days:
        print("Brak danych w zakresie — nic nie zapisuję.")
        if not args.dry_run:
            update_health("WARNING", zrodla, dni=len(istniejace),
                          ostatni_dzien=max(istniejace) if istniejace else None,
                          blad="pusty zakres")
        return

    print_table(days)

    if args.dry_run:
        print("\n[DRY-RUN] Pominięto zapis plików.")
        return

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    rows, dirty = merge(days, istniejace, stamp)

    if dirty:
        atomic_write_csv(CSV_FILE, HDR, rows)
        print(f"[ZAPIS] {CSV_FILE}")
    else:
        print("INFO: Dane w CSV są już aktualne — pomijam zapis.")

    update_health("OK", zrodla, dni=len(rows),
                  ostatni_dzien=rows[-1][1] if rows else None)
    print(f"[ZAPIS] {HEALTH_FILE} (OK)")


if __name__ == "__main__":
    main()
