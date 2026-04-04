# 🩺 ha-health-pipeline

> Customowy system monitorowania zdrowia integrujący **Xiaomi S400**, **Omron M4 Intelli IT** i **Garmin Connect** — zbudowany na Debian + Home Assistant + MQTT.

---

## 🎯 Cel projektu

- Stabilne zbieranie danych pomiarowych (bez problemów z BLE)
- Pełna kontrola danych — CSV jako source of truth
- Integracja z Home Assistant i Garmin Connect
- Odporność na restart systemu (MQTT retained + init publish)

---

## 🏗️ Architektura

### ⚖️ Xiaomi S400 (waga)

```
BLE → export2garmin → CSV → MQTT → Home Assistant
```

### 🩸 Omron M4 Intelli IT (ciśnienie)

```
Omron → Cloud → omramin → CSV ──→ MQTT → Home Assistant
                                └──→ Garmin Connect
```

---

## 📁 Struktura projektu

```
ha-project/
├── config/
│   ├── export2garmin/          # symlinki do konfiguracji export2garmin
│   └── hassio/                 # konfiguracja Home Assistant
│       ├── automations.yaml
│       ├── configuration.yaml
│       └── custom_components/  # garmin_connect, hacs, localtuya, spook…
├── external/
│   └── export2garmin/          # submoduł (waga Xiaomi)
│       └── user/               # export2garmin.cfg, backup CSV, tokeny
├── health/                     # bieżący stan zdrowia (JSON)
│   ├── garmin.json
│   ├── miscale.json
│   └── omron.json
├── jobs/omron/                 # jednorazowe i cykliczne skrypty
│   ├── fetch_garmin_stats.py
│   ├── fill_omron_csv.py
│   └── omron_loop.sh
├── publishers/
│   ├── miscale/publish_miscale_to_mqtt_daemon.py
│   └── omron/
│       ├── publish_garmin_to_mqtt_daemon.py
│       └── publish_omron_to_mqtt_daemon.py
├── systemd/                    # pliki .service
└── user -> external/export2garmin/user/
```

---

## 🚀 Setup (od zera)

### 1. Klonowanie repo

```bash
git clone https://github.com/fearer81/ha-health-pipeline
cd ha-health-pipeline
```

### 2. Instalacja export2garmin

```bash
cd external
git clone https://github.com/your-source/export2garmin.git
```

### 3. Python venv + zależności

```bash
python3 -m venv external/export2garmin/venv
source external/export2garmin/venv/bin/activate
pip install -r requirements.txt
pip install omramin
```

### 4. Konfiguracja

Edytuj `external/export2garmin/user/export2garmin.cfg` zgodnie z instrukcją projektu export2garmin.

### 5. Instalacja usług systemd

```bash
cp systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable export2garmin miscale-mqtt omron_sync omron-mqtt garmin_monitor garmin-mqtt
```

### 6. Start

```bash
systemctl start export2garmin miscale-mqtt omron_sync omron-mqtt garmin_monitor garmin-mqtt
```

---

## ⚡ Zarządzanie usługami

### Pełny restart pipeline'u

```bash
# alias: restartha
systemctl daemon-reload
rm -rf /root/ha-project/external/export2garmin/user/tmp/*
systemctl restart export2garmin garmin_monitor garmin-mqtt miscale-mqtt omron_sync omron-mqtt
```

### Sprawdzenie statusu

```bash
systemctl status export2garmin
systemctl status garmin_monitor
systemctl status garmin-mqtt
systemctl status miscale-mqtt
systemctl status omron_sync
systemctl status omron-mqtt
cat /root/ha-project/health/*
```

---

## 📜 Git — szybki workflow

```bash
# alias: gitexport
cd /root/ha-project
git status
git add .
git commit -m "Update"
git push
```

---

## 📋 Logi

### Live — wszystkie usługi

```bash
journalctl -u export2garmin -u garmin_monitor -u garmin-mqtt \
           -u miscale-mqtt -u omron_sync -u omron-mqtt \
           -f -o short-iso --no-hostname | \
sed -E '
s/bash\[[0-9]+\]: //g;
s/(export2garmin|garmin_monitor|garmin-mqtt)/\x1b[95m\1\x1b[0m/g;
s/(miscale-mqtt)/\x1b[92m\1\x1b[0m/g;
s/(omron_sync)/\x1b[93m\1\x1b[0m/g;
s/(omron-mqtt)/\x1b[91m\1\x1b[0m/g;
s/(ERROR)/\x1b[31m\1\x1b[0m/g;
s/(WARN)/\x1b[33m\1\x1b[0m/g;
s/(Downloaded|Device|successfully|SUKCES|NEW)/\x1b[92m\1\x1b[0m/g;
s/(DEBUG)/\x1b[36m\1\x1b[0m/g;
s/(CSV)/\x1b[35m\1\x1b[0m/g;
s/(START CYKLU|Cykl zakończony)/\x1b[1;37m\1\x1b[0m/g;
'
```

### Aliasy logów (ostatnie N linii)

| Alias | Usługi |
|---|---|
| `jmiscale` | export2garmin + miscale-mqtt |
| `jomron` | export2garmin + omron_sync + omron-mqtt |
| `jgarmin` | garmin_monitor + garmin-mqtt |
| `jmiscale-live` | j.w. w trybie `-f` |
| `jomron-live` | j.w. w trybie `-f` |
| `jgarmin-live` | j.w. w trybie `-f` |

#### jomron

```bash
journalctl -u export2garmin -u omron_sync -u omron-mqtt -n 50 -o short-iso --no-hostname | \
sed -E '
s/bash\[[0-9]+\]: //g;
s/(export2garmin)/\x1b[95m\1\x1b[0m/g;
s/(omron_sync)/\x1b[93m\1\x1b[0m/g;
s/(omron-mqtt)/\x1b[91m\1\x1b[0m/g;
s/(ERROR)/\x1b[31m\1\x1b[0m/g;
s/(WARN)/\x1b[33m\1\x1b[0m/g;
s/(Downloaded|Device|successfully|SUKCES|NEW)/\x1b[92m\1\x1b[0m/g;
s/(DEBUG)/\x1b[36m\1\x1b[0m/g;
s/(CSV)/\x1b[35m\1\x1b[0m/g;
s/(START CYKLU|Cykl zakończony)/\x1b[1;37m\1\x1b[0m/g;
'
```

#### jgarmin

```bash
journalctl -u garmin_monitor -u garmin-mqtt -n 50 -o short-iso --no-hostname | \
sed -E '
s/bash\[[0-9]+\]: //g;
s/(garmin_monitor|garmin-mqtt)/\x1b[95m\1\x1b[0m/g;
s/(ERROR)/\x1b[31m\1\x1b[0m/g;
s/(WARN)/\x1b[33m\1\x1b[0m/g;
s/(SUKCES|NEW)/\x1b[92m\1\x1b[0m/g;
s/(DEBUG)/\x1b[36m\1\x1b[0m/g;
'
```

#### jmiscale

```bash
journalctl -u export2garmin -u miscale-mqtt -n 50 -o short-iso --no-hostname | \
sed -E '
s/bash\[[0-9]+\]: //g;
s/(export2garmin)/\x1b[95m\1\x1b[0m/g;
s/(miscale-mqtt)/\x1b[92m\1\x1b[0m/g;
s/(ERROR)/\x1b[31m\1\x1b[0m/g;
s/(WARN)/\x1b[33m\1\x1b[0m/g;
s/(Downloaded|successfully|NEW)/\x1b[92m\1\x1b[0m/g;
'
```

---

## 🧹 MQTT — czyszczenie retained messages

> **Zasada:** CSV = source of truth → MQTT (retained) = cache.  
> Restart usług **nie** usuwa danych. Najpierw popraw CSV → czyść MQTT → restartuj daemony.

### Waga (Xiaomi S400)

```bash
mosquitto_pub -h 192.168.1.41 -u fear -P '***' -t "hubert/scale_s400/history" -r -n
mosquitto_pub -h 192.168.1.41 -u fear -P '***' -t "hubert/scale_s400/state"   -r -n
systemctl restart miscale-mqtt
```

### Ciśnienie (Omron M4)

```bash
mosquitto_pub -h 192.168.1.41 -u user -P '***' -t "hubert/omron_m4/history" -r -n
mosquitto_pub -h 192.168.1.41 -u user -P '***' -t "hubert/omron_m4/state"   -r -n
systemctl restart omron-mqtt
```

---

## 📊 Home Assistant — dashboard

- Karta: `custom:flex-table-card`
- Dane z MQTT (`rows`)
- Statusy ciśnienia: S0–S3
- Sticky headers + scroll, brak zawijania danych

---

## 🧠 Kluczowe decyzje projektowe

| Decyzja | Uzasadnienie |
|---|---|
| ❌ BLE dla Omrona | Niestabilne — zastąpione pobieraniem z chmury |
| ✅ MQTT retained + init publish | Wymagane dla HA po restarcie |
| ✅ CSV jako centralny storage | HA = wizualizacja, MQTT = transport |
| ✅ Python venv | Izolacja zależności od systemu |

---

## 📦 Dane

| Plik | Zawartość |
|---|---|
| `user/miscale_backup.csv` | Historia pomiarów wagi |
| `user/omron_backup.csv` | Historia pomiarów ciśnienia |
| `health/miscale.json` | Bieżący odczyt — waga |
| `health/omron.json` | Bieżący odczyt — ciśnienie |
| `health/garmin.json` | Bieżący odczyt — Garmin |
