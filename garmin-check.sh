#!/bin/bash

# Konfiguracja projektu
MQTT_HOST="192.168.1.41"
MQTT_USER="fear"
TOPIC="hubert/status/garmin"
ENV_FILE="/etc/default/miscale-mqtt"
VENV_PYTHON="/root/ha-project/external/export2garmin/venv/bin/python"
CONFIG_JSON="/root/.config/omramin/config.json"

# Interwały (w sekundach)
SLEEP_OK=1800    # 30 min gdy wszystko działa
SLEEP_ERR=5400   # 1.5h gdy wykryto blokadę (np. 429)

# Pobieranie hasła MQTT
if [ -f "$ENV_FILE" ]; then
    MQTT_PASS=$(grep "MQTT_PASS" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'" | tr -d ' ')
fi

echo "[$(date)] Monitor v9 (Error Code Extractor - Token fear81)..."

while true; do
    CURRENT_IP=$(curl -s http://ipinfo.io/ip --max-time 5)
    
    # Test logowania - wyciągamy kod błędu jeśli wystąpi
    STATUS=$($VENV_PYTHON -c "
import json, os, re
from garminconnect import Garmin
try:
    with open('$CONFIG_JSON', 'r') as f:
        email = json.load(f)['omron']['email']
    token_path = f'/root/ha-project/external/export2garmin/user/{email}'
    with open(token_path, 'r') as tf:
        token = tf.read()
    client = Garmin()
    client.login(token)
    print('200')
except Exception as e:
    # Szukamy dowolnego 3-cyfrowego kodu błędu w komunikacie
    match = re.search(r'(\d{3})', str(e))
    print(match.group(1) if match else 'ERR')
")

    if [[ "$STATUS" == "200" ]]; then
        MSG="✅ OK | VPN: $CURRENT_IP | Garmin: OK"
        CURRENT_SLEEP=$SLEEP_OK
    elif [[ "$STATUS" == "429" ]]; then
        MSG="❌ BLOKADA 429 (Too Many Requests) | IP: $CURRENT_IP. Wait 1.5h!"
        CURRENT_SLEEP=$SLEEP_ERR
    elif [[ "$STATUS" == "403" ]]; then
        MSG="🚫 BŁĄD 403 (Forbidden/Ban) | IP: $CURRENT_IP. Zmień VPN!"
        CURRENT_SLEEP=$SLEEP_ERR
    elif [[ "$STATUS" == "401" ]]; then
        MSG="🔑 BŁĄD 401 (Unauthorized) | IP: $CURRENT_IP. Token wygasł!"
        CURRENT_SLEEP=$SLEEP_OK
    else
        MSG="⚠️ BŁĄD $STATUS | IP: $CURRENT_IP. Sprawdź logi."
        CURRENT_SLEEP=$SLEEP_OK
    fi

    # Publikacja i logowanie
    echo "[$(date)] $MSG"
    mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" -t "$TOPIC" -m "$MSG" -r

    sleep $CURRENT_SLEEP
done
