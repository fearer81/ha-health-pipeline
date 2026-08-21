#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostyka: pobiera kroki dzienne + aktywności z Garmin Connect
i drukuje tabelę do porównania z eksportem CSV.

NIC nie zapisuje (poza opcjonalnym --save do /tmp). Nie dotyka MQTT.

Użycie:
  python3 kroki_compare.py            # tabela
  python3 kroki_compare.py --dump     # + surowy JSON pierwszej aktywności
  python3 kroki_compare.py --save     # + zrzut surowych odpowiedzi do /tmp
"""

import os
import sys
import json
from datetime import date, datetime

import garth
from garminconnect import Garmin

# --- KONFIGURACJA (spójna z jobs/omron/fetch_garmin_stats.py) ---
BASE_PATH = "/root/ha-project/external/export2garmin"
CONFIG_PATH = "/root/.config/omramin/config.json"

START = "2026-08-15"
END = date.today().isoformat()

DUMP = "--dump" in sys.argv
SAVE = "--save" in sys.argv

DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]


def login():
    if not os.path.exists(CONFIG_PATH):
        sys.exit("BŁĄD: Brak pliku konfiguracyjnego.")

    with open(CONFIG_PATH, "r") as f:
        conf = json.load(f)

    garth.configure(domain="garmin.com")

    token_path = f"{BASE_PATH}/user/{conf['omron']['email']}"
    if not os.path.exists(token_path):
        sys.exit(f"BŁĄD: Brak tokena w {token_path}")

    with open(token_path, "r") as tf:
        client = Garmin()
        client.login(tf.read())

    return client


def pick(d, *names):
    """Zwraca pierwszą niepustą wartość spośród podanych kluczy."""
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


def act_steps(a):
    """Zwraca (kroki, nazwa_pola). Wykrywa nazwę pola dynamicznie."""
    for k in ("steps", "totalSteps"):
        if a.get(k) is not None:
            return int(a[k]), k
    for k, v in a.items():
        if "step" in k.lower() and isinstance(v, (int, float)):
            return int(v), k
    return 0, None


def fetch_daily(client):
    """Kroki dzienne. Preferuje get_daily_steps (1 request), fallback na get_stats."""
    try:
        rows = client.get_daily_steps(START, END) or []
        out = {}
        for r in rows:
            day = pick(r, "calendarDate", "statisticsStartDate")
            tot = pick(r, "totalSteps", "steps")
            goal = pick(r, "stepGoal", "dailyStepGoal", "stepsGoal")
            if day:
                out[day] = (int(tot or 0), int(goal or 0))
        print(f"[API] get_daily_steps: {len(out)} dni, 1 request")
        return out, rows
    except Exception as e:
        print(f"[API] get_daily_steps nie zadziałało ({e}) — fallback na get_stats")

    out, raw = {}, []
    d0 = datetime.strptime(START, "%Y-%m-%d").date()
    d1 = datetime.strptime(END, "%Y-%m-%d").date()
    cur = d0
    while cur <= d1:
        s = client.get_stats(cur.isoformat()) or {}
        raw.append(s)
        out[cur.isoformat()] = (
            int(pick(s, "totalSteps") or 0),
            int(pick(s, "dailyStepGoal", "stepGoal") or 0),
        )
        cur = date.fromordinal(cur.toordinal() + 1)
    print(f"[API] get_stats: {len(out)} dni, {len(out)} requestów")
    return out, raw


def fetch_acts(client):
    acts = client.get_activities_by_date(START, END) or []
    print(f"[API] get_activities_by_date: {len(acts)} aktywności, 1 request")
    return acts


def main():
    client = login()

    daily, daily_raw = fetch_daily(client)
    acts = fetch_acts(client)

    if SAVE:
        with open("/tmp/kroki_daily_raw.json", "w", encoding="utf-8") as f:
            json.dump(daily_raw, f, indent=2, ensure_ascii=False)
        with open("/tmp/kroki_acts_raw.json", "w", encoding="utf-8") as f:
            json.dump(acts, f, indent=2, ensure_ascii=False)
        print("[SAVE] /tmp/kroki_daily_raw.json, /tmp/kroki_acts_raw.json")

    if DUMP and acts:
        print("\n=== SUROWY JSON PIERWSZEJ AKTYWNOŚCI ===")
        print(json.dumps(acts[0], indent=2, ensure_ascii=False))
        print("=== KLUCZE ZAWIERAJĄCE 'step' ===")
        print([k for k in acts[0] if "step" in k.lower()] or "BRAK!")
        print()

    # --- grupowanie aktywności po dniach ---
    per_day = {}
    field_used = set()
    for a in acts:
        st = pick(a, "startTimeLocal", "startTimeGMT") or ""
        day = st.split(" ")[0]
        if not day:
            continue
        steps, field = act_steps(a)
        if field:
            field_used.add(field)
        typ = (a.get("activityType") or {}).get("typeKey", "?")
        per_day.setdefault(day, []).append({
            "godz": st.split(" ")[1][:5] if " " in st else "",
            "typ": typ,
            "nazwa": a.get("activityName", ""),
            "kroki": steps,
        })

    print(f"[POLE] kroki w aktywnościach odczytane z: {field_used or 'BRAK — wszystkie 0!'}")

    # --- tabela ---
    print("\n" + "=" * 78)
    print(f"{'Dzień':<14}{'Aktywn.':>10}{'Dzienne':>10}{'Cel':>8}"
          f"{'Różnica':>10}{'Poza akt.':>11}{'Flaga':>12}")
    print("=" * 78)

    sum_a = sum_d = sum_p = 0
    for day in sorted(set(list(daily.keys()) + list(per_day.keys()))):
        tot, goal = daily.get(day, (0, 0))
        sa = sum(x["kroki"] for x in per_day.get(day, []))
        diff = tot - sa
        poza = max(0, diff)
        flag = "ROZBIEŻNOŚĆ" if diff < 0 else ""
        dn = DNI[datetime.strptime(day, "%Y-%m-%d").weekday()]
        print(f"{day} {dn:<4}{sa:>10,}{tot:>10,}{goal:>8,}"
              f"{diff:>10,}{poza:>11,}{flag:>12}".replace(",", " "))
        sum_a += sa
        sum_d += tot
        sum_p += poza

    print("-" * 78)
    print(f"{'RAZEM':<14}{sum_a:>10,}{sum_d:>10,}{'':>8}{'':>10}{sum_p:>11,}"
          .replace(",", " "))
    print("=" * 78)

    # --- szczegóły aktywności ---
    print("\nAktywności wg dni:")
    for day in sorted(per_day):
        for x in per_day[day]:
            print(f"  {day} {x['godz']}  {x['typ']:<22} {x['kroki']:>7,} "
                  f" {x['nazwa']}".replace(",", " "))


if __name__ == "__main__":
    main()
