# 🔒 Production Hardening

> Dokumentacja odporności, bezpieczeństwa i monitorowania systemu  
> **Stack:** OpenWrt router → Debian host → Home Assistant + MQTT + Health pipeline

---

## Spis treści

1. [Przegląd architektury](#1-przegląd-architektury)
2. [Router — OpenWrt](#2-router--openwrt)
3. [VPN — WireGuard / ProtonVPN / WARP](#3-vpn--wireguard--protonvpn--warp)
4. [Watchdog sieciowy](#4-watchdog-sieciowy)
5. [Home Assistant](#5-home-assistant)
6. [MQTT (Mosquitto)](#6-mqtt-mosquitto)
7. [Systemd — usługi health pipeline](#7-systemd--usługi-health-pipeline)
8. [Sekrety i dane wrażliwe](#8-sekrety-i-dane-wrażliwe)
9. [Backup i odtwarzanie](#9-backup-i-odtwarzanie)
10. [Znane problemy i obejścia](#10-znane-problemy-i-obejścia)

---

## 1. Przegląd architektury

```
Internet
   │
   ▼
[OpenWrt router]
   ├── WireGuard VPN (ProtonVPN: NL / USA)
   ├── WARP (fallback)
   ├── selective routing (vpn-domains.list)
   └── watchdog ping → reboot
   │
   ▼
[Debian host — 192.168.1.x]
   ├── Home Assistant (Docker/supervised)
   ├── Mosquitto MQTT broker
   ├── export2garmin (waga Xiaomi S400)
   ├── omramin (ciśnienie Omron M4)
   └── systemd services (6 usług)
```

---

## 2. Router — OpenWrt

### Zasady ogólne

- **Żaden port administracyjny (LuCI, SSH) nie jest wystawiony na WAN.**
- SSH dostępny tylko z sieci lokalnej (192.168.1.0/24).
- Hasło roota ustawione, logowanie kluczem preferowane.
- Logi systemowe: `logread` / `logread -f`

### Weryfikacja otwartych portów (z zewnątrz)

```bash
# Na routerze:
nmap -sT localhost

# Z hosta LAN:
nmap -p 22,80,443,8080 192.168.1.1
```

### Aktualizacje

```bash
opkg update
opkg list-upgradable
opkg upgrade <pakiet>
```

> ⚠️ Nigdy `opkg upgrade` w całości — może złamać zależności WireGuard/kmod.

### Przywracanie konfiguracji

Konfiguracja sieci jest wersjonowana w repozytorium:

```
config/router/config → /etc/config/  (symlink)
```

Aby przywrócić po factory reset:

```bash
# 1. Skopiuj pliki z repo
cp config/router/config/network /etc/config/network
cp config/router/config/firewall /etc/config/firewall

# 2. Wgraj skrypty
cp config/router/toggle-vpn /root/toggle-vpn
cp config/router/apply-vpn.sh /root/apply-vpn.sh
cp config/router/switch-provider.sh /root/switch-provider.sh
cp config/router/testping.sh /root/testping.sh
chmod +x /root/*.sh /root/toggle-vpn

# 3. Załaduj konfigurację
reload_config
```

---

## 3. VPN — WireGuard / ProtonVPN / WARP

### Dostępne konfiguracje

| Plik | Kraj | Dostawca |
|---|---|---|
| `vpn-configs/holandia.conf` | 🇳🇱 Holandia | ProtonVPN |
| `vpn-configs/usa.conf` | 🇺🇸 USA | ProtonVPN |
| (wbudowane) | — | Cloudflare WARP |

### Zmiana aktywnego serwera VPN

```bash
# Podmień kraj (parsuje .conf, wpisuje do /etc/config/network, czeka na handshake)
/root/apply-vpn.sh /root/vpn-configs/holandia.conf
/root/apply-vpn.sh /root/vpn-configs/usa.conf
```

### Zmiana dostawcy (ProtonVPN ↔ WARP)

```bash
/root/switch-provider.sh PROTON
/root/switch-provider.sh WARP
```

Skrypt zachowuje aktualny tryb routingu (GLOBAL / SELECTIVE / INACTIVE) i po zmianie dostawcy przywraca ten sam tryb.

### Tryby routingu

```bash
/root/toggle-vpn on           # cały ruch przez VPN (reguła ip: 50)
/root/toggle-vpn selective_on # tylko domeny z vpn-domains.list (reguła ip: 45)
/root/toggle-vpn off          # VPN wyłączony
```

### Odświeżanie domen w selective routing

```bash
/root/vpn-refresh-domains
```

Pobiera aktualne adresy IP dla domen z `vpn-domains.list` i wpisuje je do tablicy routingu.

### Weryfikacja stanu VPN

```bash
wg show PROTON
ip rule show
ip route show table 200
curl --interface PROTON https://ipinfo.io/ip
```

### Co robić gdy VPN nie wstaje

```bash
# 1. Sprawdź logi
logread | grep -i wireguard

# 2. Wymuś restart
ifdown PROTON
ip link delete PROTON 2>/dev/null
sleep 2
ifup PROTON

# 3. Jeśli nie pomaga — ponów apply-vpn z tym samym plikiem
/root/apply-vpn.sh /root/vpn-configs/holandia.conf
```

> ⚠️ Klucze WireGuard mają 44 znaki Base64. `apply-vpn.sh` automatycznie poprawia klucze o długości 43 (dodaje `=`).

---

## 4. Watchdog sieciowy

### Mechanizm

`testping.sh` odpytuje `8.8.8.8`. Jeśli brak odpowiedzi → reboot routera.  
Uruchamiany przez **cron** co kilka minut.

```bash
# Sprawdź wpis cron:
crontab -l | grep testping
```

Typowy wpis:

```
*/5 * * * * /root/testping.sh
```

### Logi

```bash
cat /root/inetmonit.log        # tylko restarty (NOK)
logread | grep testpinglog     # OK i NOK przez syslog
```

### Historia restartów (inetmonit.log)

```
Sun Feb  1 20:30:10 CET 2026   — 1 restart
Tue Feb 10 20:20:00 CET 2026   — 1 restart
Sun Mar  1 21:20:xx CET 2026   — 8 restartów (burst — prawdopodobnie awaria łącza)
Wed Mar 11 23:10–23:20          — 2 restarty
Thu Mar 12 19:20:10             — 1 restart
Sat Mar 28 18:40:00             — 1 restart
Mon Mar 30 19:40:00             — 1 restart
```

> Burst z 1 marca (8 restartów ~20:20) wskazuje na dłuższą awarię łącza lub pętle startową. Warto rozważyć backoff — nie restartować częściej niż co 10 minut.

### Zalecana poprawa testping.sh (backoff)

```sh
#!/bin/sh
LOCKFILE="/tmp/testping.lock"
LAST_REBOOT="/tmp/testping_last_reboot"
MIN_INTERVAL=600  # 10 minut między restartami

if [ -f "$LOCKFILE" ]; then exit 0; fi
touch "$LOCKFILE"

if /bin/ping -q -c 2 -W 3 8.8.8.8 > /dev/null 2>&1; then
    logger -p notice -t testpinglog "OK"
else
    NOW=$(date +%s)
    LAST=$(cat "$LAST_REBOOT" 2>/dev/null || echo 0)
    if [ $((NOW - LAST)) -ge $MIN_INTERVAL ]; then
        echo "$(date) ===-> NOK! Rebooting!" >> /root/inetmonit.log
        logger -p err -t testpinglog "NOK! Rebooting!"
        echo "$NOW" > "$LAST_REBOOT"
        rm -f "$LOCKFILE"
        /sbin/reboot
    else
        logger -p warn -t testpinglog "NOK! Reboot wstrzymany (backoff)"
    fi
fi

rm -f "$LOCKFILE"
```

---

## 5. Home Assistant

### Bezpieczeństwo dostępu

- **Dostęp z internetu:** wyłącznie przez VPN lub Nabu Casa (szyfrowany tunnel).
- Port 8123 **nie jest wystawiony bezpośrednio na WAN** przez router.
- 2FA włączone dla kont administracyjnych.
- Silne hasła, bez domyślnych danych logowania.

### Kopie konfiguracji

Pliki konfiguracyjne są wersjonowane w repo (`config/hassio/`).  
Kopie z datą w nazwie tworzone ręcznie przed większymi zmianami:

```
automations_kopia_251214.yaml
automations_kopia_260329.yaml
configuration_kopia_251204.yaml
configuration_kopia_260329.yaml
```

> 💡 Rozważ automatyczny backup przez `git commit` po każdej zmianie via HA automation.

### Sekrety HA

Dane wrażliwe (tokeny, hasła) przechowywane w `secrets.yaml`, nigdy inline w konfiguracji.

```yaml
# configuration.yaml
mqtt:
  password: !secret mqtt_password
```

```bash
# Sprawdź czy secrets.yaml nie trafia do repo:
cat .gitignore | grep secrets
```

### Restart HA po awarii

```bash
# Status kontenera / procesu
systemctl status homeassistant   # lub
docker ps | grep homeassistant

# Restart
systemctl restart homeassistant
```

### Weryfikacja logu HA

```bash
tail -f /root/ha-project/config/hassio/home-assistant.log
```

> ⚠️ Pliki `.db.corrupt.*` w katalogu hassio wskazują na 3 uszkodzenia bazy danych we wrześniu 2025 — prawdopodobnie przerwane zasilanie. Rozważ UPS lub graceful shutdown script.

---

## 6. MQTT (Mosquitto)

### Zasady bezpieczeństwa

- Broker dostępny tylko w sieci lokalnej (bind na 192.168.1.x lub localhost).
- **Anonimowy dostęp wyłączony** (`allow_anonymous false`).
- Osobne konta dla każdego producenta danych.
- Hasła haszowane przez `mosquitto_passwd`.

### Weryfikacja konfiguracji

```bash
cat /etc/mosquitto/mosquitto.conf | grep -E "allow_anonymous|listener|password_file"
```

### Testowanie połączenia

```bash
mosquitto_sub -h 192.168.1.41 -u fear -P '***' -t "hubert/#" -v
```

### Tematy MQTT i ich znaczenie

| Temat | Zawartość | Retained |
|---|---|---|
| `hubert/scale_s400/state` | Ostatni pomiar wagi | ✅ |
| `hubert/scale_s400/history` | Historia pomiarów (JSON array) | ✅ |
| `hubert/omron_m4/state` | Ostatni pomiar ciśnienia | ✅ |
| `hubert/omron_m4/history` | Historia pomiarów (JSON array) | ✅ |

> **Retained messages** są kluczowe — HA po restarcie odczytuje ostatnią wartość bez czekania na nowy pomiar.

### Czyszczenie retained messages

```bash
# Wyczyść temat (pusta wiadomość retained = usunięcie)
mosquitto_pub -h 192.168.1.41 -u USER -P '***' -t "TEMAT" -r -n

# Następnie zawsze zrestartuj odpowiedniego daemona
systemctl restart miscale-mqtt   # lub omron-mqtt
```

---

## 7. Systemd — usługi health pipeline

### Mapa usług

| Usługa | Rola | Zależy od |
|---|---|---|
| `export2garmin` | Eksport danych wagi do Garmin Connect | — |
| `miscale-mqtt` | Publikuje dane wagi na MQTT | export2garmin |
| `omron_sync` | Pobiera dane ciśnienia z chmury Omron | — |
| `omron-mqtt` | Publikuje dane ciśnienia na MQTT | omron_sync |
| `garmin_monitor` | Monitoruje dane Garmin Connect | export2garmin |
| `garmin-mqtt` | Publikuje dane Garmin na MQTT | garmin_monitor |

### Sprawdzenie stanu wszystkich usług

```bash
for svc in export2garmin miscale-mqtt omron_sync omron-mqtt garmin_monitor garmin-mqtt; do
    echo "=== $svc ==="
    systemctl is-active $svc
done
```

### Pełny restart pipeline

```bash
systemctl daemon-reload
rm -rf /root/ha-project/external/export2garmin/user/tmp/*
systemctl restart export2garmin garmin_monitor garmin-mqtt miscale-mqtt omron_sync omron-mqtt
```

### Co robić gdy usługa nie startuje

```bash
# 1. Sprawdź log
journalctl -u NAZWA_USŁUGI -n 50 --no-pager

# 2. Sprawdź czy Python venv jest aktywny w .service
grep ExecStart /etc/systemd/system/NAZWA_USŁUGI.service

# 3. Sprawdź lock/pid z poprzedniej sesji
ls /root/ha-project/external/export2garmin/user/tmp/
rm -f /root/ha-project/external/export2garmin/user/tmp/import.lock
rm -f /root/ha-project/external/export2garmin/user/tmp/import.pid
```

### Zalecana konfiguracja .service (odporność na awarie)

```ini
[Service]
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5
```

---

## 8. Sekrety i dane wrażliwe

### Czego NIE commitować do repo

```gitignore
# .gitignore — minimalne wymagania
config/hassio/secrets.yaml
external/export2garmin/user/export2garmin.cfg
external/export2garmin/user/fear81@gmail.com
external/export2garmin/user/garmin_stats.csv
external/export2garmin/user/import_tokens.py
config/router/vpn-configs/
*.conf
*.key
*.token
```

### Weryfikacja przed pushem

```bash
# Sprawdź czy nie ma sekretów w staged zmianach
git diff --cached | grep -iE "password|token|secret|key|PrivateKey"

# Przeszukaj całe repo
git grep -iE "password|token|PrivateKey" -- '*.yaml' '*.py' '*.sh' '*.cfg'
```

### Gdzie są przechowywane sekrety

| Sekret | Lokalizacja | Typ |
|---|---|---|
| Hasła MQTT | `/etc/mosquitto/passwd` | hasz bcrypt |
| Tokeny Garmin | `user/import_tokens.py` | plaintext — chronić! |
| Konfiguracja export2garmin | `user/export2garmin.cfg` | może zawierać dane konta |
| Klucze WireGuard | `vpn-configs/*.conf` | plaintext — **nie commitować** |
| Sekrety HA | `config/hassio/secrets.yaml` | plaintext — nie commitować |

---

## 9. Backup i odtwarzanie

### Co backupować

| Zasób | Lokalizacja | Priorytet |
|---|---|---|
| Dane CSV (source of truth) | `user/miscale_backup.csv`, `user/omron_backup.csv` | 🔴 Krytyczny |
| Konfiguracja HA | `config/hassio/configuration.yaml`, `automations.yaml` | 🔴 Krytyczny |
| Baza danych HA | `config/hassio/home-assistant_v2.db` | 🟡 Ważny |
| Tokeny Garmin | `user/import_tokens.py`, `user/fear81@gmail.com` | 🔴 Krytyczny |
| Konfiguracja routera | `config/router/config/` | 🟡 Ważny |
| Pliki .service | `systemd/` | 🟢 Pomocniczy |

### Szybki backup CSV

```bash
DATE=$(date +%Y%m%d)
cp user/miscale_backup.csv user/miscale_backup_${DATE}.csv
cp user/omron_backup.csv   user/omron_backup_${DATE}.csv
```

### Odtwarzanie po awarii hosta

```bash
# 1. Przywróć repo
git clone https://github.com/fearer81/ha-health-pipeline /root/ha-project

# 2. Przywróć sekrety (z zaszyfrowanego backupu offline)
cp /backup/secrets.yaml config/hassio/secrets.yaml
cp /backup/import_tokens.py external/export2garmin/user/import_tokens.py

# 3. Przywróć CSV (source of truth)
cp /backup/miscale_backup.csv external/export2garmin/user/miscale_backup.csv
cp /backup/omron_backup.csv   external/export2garmin/user/omron_backup.csv

# 4. Zainstaluj venv
cd /root/ha-project
python3 -m venv external/export2garmin/venv
source external/export2garmin/venv/bin/activate
pip install -r requirements.txt omramin

# 5. Zainstaluj i uruchom usługi
cp systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now export2garmin miscale-mqtt omron_sync omron-mqtt garmin_monitor garmin-mqtt
```

---

## 10. Znane problemy i obejścia

### Uszkodzenia bazy danych HA (wrzesień 2025)

Trzy pliki `.db.corrupt.*` wskazują na nagłe przerwanie zasilania lub restart hosta podczas zapisu.

**Obejście bieżące:** HA automatycznie tworzy nową bazę po wykryciu uszkodzenia.  
**Zalecenie:** UPS lub skonfigurować `systemd` shutdown hook, który przed wyłączeniem zatrzymuje HA.

### Burst restartów routera (marzec 2025 — 8 restartów w ~1 min)

`testping.sh` bez backoffu powoduje pętle restartów gdy łącze jest niestabilne.

**Zalecenie:** Zastąp aktualny `testping.sh` wersją z backoffem opisaną w sekcji 4.

### MQTT retained po restarcie daemona

Demony nie usuwają starych retained messages po restarcie — HA widzi stare dane do czasu pierwszego nowego pomiaru.

**Obejście:** Przed restartem zawsze czyść retained:

```bash
mosquitto_pub -h 192.168.1.41 -u USER -P '***' -t "TEMAT" -r -n
```

### Tokeny Garmin wygasają

`import_tokens.py` zawiera tokeny sesji Garmin Connect, które mogą wygasać.

**Obejście:** Uruchom ponownie procedurę autentykacji przez `omramin` lub `garth`:

```bash
source external/export2garmin/venv/bin/activate
python3 -c "import garth; garth.login('email', 'password'); garth.save('~/.garth')"
```

### VPN — klucze Base64 o długości 43 znaków

ProtonVPN czasem eksportuje klucze bez paddingu (`=`). `apply-vpn.sh` to obsługuje automatycznie.

---

*Ostatnia aktualizacja: 2026-04*
