#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pobiera z Garmin Connect kroki, dystans, pływanie i kalorie; zapisuje do CSV.

  user/kroki.csv     - jeden wiersz na dzień; nowe dni dopisywane,
                       istniejące aktualizowane (klucz = Date)
  health/kroki.json  - heartbeat + lastSync zegarka

Pływanie (parentTypeId 26) NIE wchodzi do dystansu lądowego - Garmin nie
dolicza go do totalDistance. Ma własne kolumny. Czas liczony wspólnie.

Kalorie = totalKilocalories z get_stats, czyli całodobowa suma spalonych
kalorii (to samo, co "Suma kalorii" w aplikacji Garmin Connect).
get_stats to 1 request NA DZIEŃ, więc pobierany tylko dla dni nowych
lub z zakładki; starsze wartości brane z CSV.

Scalanie po NAZWACH kolumn - dołożenie kolumny nie psuje starych wierszy.
"""

import os
import sys
import csv
import json
import time
import argparse
from datetime import date, datetime, timedelta, timezone

import garth
from garminconnect import Garmin

# --- KONFIGURACJA ---
BASE_PATH = "/root/ha-project/external/export2garmin"
CONFIG_PATH = "/root/.config/omramin/config.json"

CSV_FILE = f"{BASE_PATH}/user/kroki.csv"
HEALTH_FILE = "/root/ha-project/health/kroki.json"

OVERLAP_DAYS = 3
INITIAL_DAYS = 30

# Garmin: parentTypeId 26 = swimming (lap_swimming, open_water_swimming, ...)
SWIM_PARENT_ID = 26

DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]

HDR = [
    "Unix Time", "Date", "Daily Steps", "Activity Steps",
    "Daily Distance [km]", "Distance [km]",
    "Swim Distance [km]", "Swim Lengths",
    "Duration [hh:mm:ss]", "Calories [kcal]", "Last Update",
]

COLS_DANE = [c for c in HDR if c != "Last Update"]


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
            rd = csv.DictReader(f, delimiter=";")
            if not rd.fieldnames or "Date" not in rd.fieldnames:
                print("[CSV] nieznany nagłówek — plik budowany od zera")
                return {}

            nowe_kol = [c for c in HDR if c not in rd.fieldnames]
            if nowe_kol:
                print(f"[CSV] nowe kolumny: {', '.join(nowe_kol)} "
                      f"(stare wiersze zostaną puste do odświeżenia)")

            out = {}
            for r in rd:
                d = (r.get("Date") or "").strip()
                if d:
                    out[d] = {k: (v or "").strip() for k, v in r.items() if k}
            return out
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


# ===== LAST SYNC =====
def fetch_last_sync(client):
    try:
        stats = client.get_stats(date.today().isoformat()) or {}
        raw = stats.get("lastSyncTimestampGMT")
        if not raw:
            return None, None

        dt = datetime.fromisoformat(raw.replace(" ", "T").split(".")[0]) \
                     .replace(tzinfo=timezone.utc).astimezone()
        wiek = int((datetime.now().astimezone() - dt).total_seconds() / 60)
        print(f"[SYNC] zegarek: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({wiek} min temu)")
        return dt.strftime("%Y-%m-%dT%H:%M:%S"), wiek
    except Exception as e:
        print(f"[SYNC] nieznany ({e})")
        return None, None


# ===== HEALTH =====
def update_health(status, zrodla, dni=0, ostatni_dzien=None, blad=None,
                  last_sync=None, sync_age_min=None):
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
        if last_sync:
            data["last_sync"] = last_sync
            data["sync_age_min"] = sync_age_min
            data["sync_status"] = "OK" if (sync_age_min or 0) < 180 else "STALE"
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
            float(pick(r, "totalDistance", "totalDistanceMeters") or 0),
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

        at = a.get("activityType") or {}
        plywanie = at.get("parentTypeId") == SWIM_PARENT_ID

        out.setdefault(day, []).append({
            "godzina": st.split(" ")[1][:5],
            "typ": at.get("typeKey", "?"),
            "plywanie": plywanie,
            "kroki": int(pick(a, "steps", "totalSteps") or 0),
            "dystans_km": round(float(pick(a, "distance") or 0) / 1000, 2),
            "dlugosci": int(pick(a, "activeLengths") or 0) if plywanie else 0,
            "czas_s": int(round(float(pick(a, "duration") or 0))),
        })

    for day in out:
        out[day].sort(key=lambda x: x["godzina"])

    wiele = {d: len(v) for d, v in out.items() if len(v) > 1}
    if wiele:
        print(f"[AKT] dni z kilkoma aktywnościami: "
              f"{', '.join(f'{d} x{n}' for d, n in sorted(wiele.items()))}")

    plyw = {d: sum(1 for a in v if a["plywanie"]) for d, v in out.items()}
    plyw = {d: n for d, n in plyw.items() if n}
    if plyw:
        print(f"[PŁYW] dni z pływaniem: "
              f"{', '.join(f'{d} x{n}' for d, n in sorted(plyw.items()))} "
              f"(wyłączone z dystansu lądowego)")
    return out


def fetch_kalorie(client, dni, istniejace):
    """Całodobowe kalorie z get_stats — 1 request na dzień.
    Pobiera tylko dni nowe lub z zakładki; resztę bierze z CSV."""
    prog = (date.today() - timedelta(days=OVERLAP_DAYS)).isoformat()
    out, z_csv, pobrane = {}, 0, 0

    for d in dni:
        stary = istniejace.get(d)
        if stary and d < prog and stary.get("Calories [kcal]", "").strip():
            out[d] = int(stary.get("Calories [kcal]") or 0)
            z_csv += 1
            continue

        try:
            s = client.get_stats(d) or {}
            out[d] = int(pick(s, "totalKilocalories") or 0)
            pobrane += 1
        except Exception as e:
            print(f"[KCAL] {d}: błąd ({e})")
            out[d] = 0

    print(f"[API] get_stats: {pobrane} requestów (z CSV: {z_csv})")
    return out


# ===== BUDOWA REKORDÓW =====
def build_days(daily, per_day, kalorie):
    days = []
    for d in sorted(set(list(daily.keys()) + list(per_day.keys()))):
        acts = per_day.get(d, [])
        tot, dyst_m, cel = daily.get(d, (0, 0.0, 0))

        lad = [a for a in acts if not a["plywanie"]]
        woda = [a for a in acts if a["plywanie"]]

        suma_akt = sum(a["kroki"] for a in lad)
        dyst_akt = round(sum(a["dystans_km"] for a in lad), 2)
        dyst_swim = round(sum(a["dystans_km"] for a in woda), 2)
        dlug_swim = sum(a["dlugosci"] for a in woda)
        dyst_dzien = round(dyst_m / 1000, 2)
        czas_s = sum(a["czas_s"] for a in acts)

        days.append({
            "data": d,
            "dzien": DNI[datetime.strptime(d, "%Y-%m-%d").weekday()],
            "kroki_dzienne": tot,
            "cel": cel,
            "kroki_aktywnosci": suma_akt,
            "poza_kroki": max(0, tot - suma_akt),
            "roznica": tot - suma_akt,
            "rozbieznosc": (tot - suma_akt) < 0 or (dyst_dzien - dyst_akt) < 0,
            "liczba_aktywnosci": len(acts),
            "dystans_dzienny": dyst_dzien,
            "dystans_aktywnosci": dyst_akt,
            "poza_dystans": round(max(0.0, dyst_dzien - dyst_akt), 2),
            "swim_km": dyst_swim,
            "swim_dlugosci": dlug_swim,
            "czas_s": czas_s,
            "czas": hhmmss(czas_s),
            "kcal": kalorie.get(d, 0),
        })
    return days


def row_dict(d, stamp):
    return {
        "Unix Time": str(day_ts(d["data"])),
        "Date": d["data"],
        "Daily Steps": str(d["kroki_dzienne"]),
        "Activity Steps": str(d["kroki_aktywnosci"]),
        "Daily Distance [km]": f"{d['dystans_dzienny']:.2f}",
        "Distance [km]": f"{d['dystans_aktywnosci']:.2f}",
        "Swim Distance [km]": f"{d['swim_km']:.2f}",
        "Swim Lengths": str(d["swim_dlugosci"]),
        "Duration [hh:mm:ss]": d["czas"],
        "Calories [kcal]": str(d["kcal"]),
        "Last Update": stamp,
    }


def merge(days, istniejace, stamp):
    idx = dict(istniejace)
    dopisane = zmienione = bez_zmian = 0

    for d in days:
        nowy = row_dict(d, stamp)
        stary = idx.get(d["data"])
        if stary is None:
            idx[d["data"]] = nowy
            dopisane += 1
        elif any(stary.get(c, "") != nowy[c] for c in COLS_DANE):
            idx[d["data"]] = nowy
            zmienione += 1
        else:
            bez_zmian += 1

    rows = [[r.get(c, "") for c in HDR]
            for _, r in sorted(idx.items(), key=lambda kv: kv[0])]

    print(f"[CSV] {len(rows)} dni w pliku "
          f"(dopisane: {dopisane}, zaktualizowane: {zmienione}, bez zmian: {bez_zmian})")
    return rows, dopisane + zmienione


# ===== RAPORT =====
def print_table(days):
    print("\n" + "=" * 114)
    print(f"{'Dzień':<14}{'Kroki dz.':>10}{'Kroki akt.':>11}{'n':>3}"
          f"{'Dyst. dz.':>10}{'Dyst. akt.':>11}{'Poza km':>9}"
          f"{'Basen km':>10}{'Dług.':>7}{'Czas':>10}{'kcal':>8}{'Flaga':>14}")
    print("=" * 114)
    for d in days:
        flag = "ROZBIEŻNOŚĆ" if d["rozbieznosc"] else ""
        print(f"{d['data']} {d['dzien']:<4}"
              f"{d['kroki_dzienne']:>10,}{d['kroki_aktywnosci']:>11,}"
              f"{d['liczba_aktywnosci']:>3}"
              f"{d['dystans_dzienny']:>10.2f}{d['dystans_aktywnosci']:>11.2f}"
              f"{d['poza_dystans']:>9.2f}"
              f"{d['swim_km']:>10.2f}{d['swim_dlugosci']:>7}"
              f"{d['czas']:>10}{d['kcal']:>8,}{flag:>14}".replace(",", " "))
    print("-" * 114)
    print(f"{'RAZEM':<14}"
          f"{sum(d['kroki_dzienne'] for d in days):>10,}"
          f"{sum(d['kroki_aktywnosci'] for d in days):>11,}"
          f"{sum(d['liczba_aktywnosci'] for d in days):>3}"
          f"{sum(d['dystans_dzienny'] for d in days):>10.2f}"
          f"{sum(d['dystans_aktywnosci'] for d in days):>11.2f}"
          f"{sum(d['poza_dystans'] for d in days):>9.2f}"
          f"{sum(d['swim_km'] for d in days):>10.2f}"
          f"{sum(d['swim_dlugosci'] for d in days):>7}"
          f"{hhmmss(sum(d['czas_s'] for d in days)):>10}"
          f"{sum(d['kcal'] for d in days):>8,}".replace(",", " "))
    print("=" * 114)


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

    last_sync, sync_age = fetch_last_sync(client)

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
                          ostatni_dzien=max(istniejace) if istniejace else None,
                          blad=blad, last_sync=last_sync, sync_age_min=sync_age)
        sys.exit(1)

    dni_zakres = sorted(set(list(daily.keys()) + list(per_day.keys())))
    if len(dni_zakres) > 60:
        print(f"[KCAL] UWAGA: {len(dni_zakres)} dni w zakresie — "
              f"tyle może być requestów do get_stats")
    kalorie = fetch_kalorie(client, dni_zakres, istniejace)

    days = build_days(daily, per_day, kalorie)
    if not days:
        print("Brak danych w zakresie — nic nie zapisuję.")
        if not args.dry_run:
            update_health("WARNING", zrodla, dni=len(istniejace),
                          ostatni_dzien=max(istniejace) if istniejace else None,
                          blad="pusty zakres", last_sync=last_sync, sync_age_min=sync_age)
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
                  ostatni_dzien=rows[-1][1] if rows else None,
                  last_sync=last_sync, sync_age_min=sync_age)
    print(f"[ZAPIS] {HEALTH_FILE} (OK)")


if __name__ == "__main__":
    main()
