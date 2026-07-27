#!/bin/sh
FILE=$1

if [ ! -f "$FILE" ]; then
    echo "Błąd: Brak pliku $FILE"
    exit 1
fi

# 1. WYŁĄCZAMY VPN (Czysty start)
/root/toggle-vpn off
ifdown PROTON
ip link delete PROTON 2>/dev/null

# 2. PARSOWANIE DANYCH
PRIV_KEY=$(grep "^[[:space:]]*PrivateKey" "$FILE" | awk -F'=[ ]*' '{print $2}' | tr -d '\r' | xargs)
ADDR=$(grep "^[[:space:]]*Address" "$FILE" | awk -F'=[ ]*' '{print $2}' | cut -d',' -f1 | tr -d '\r' | xargs)
PUB_KEY=$(grep "^[[:space:]]*PublicKey" "$FILE" | awk -F'=[ ]*' '{print $2}' | tr -d '\r' | xargs)
ENDPOINT=$(grep "^[[:space:]]*Endpoint" "$FILE" | awk -F'=[ ]*' '{print $2}' | tr -d '\r' | xargs)
HOST=$(echo $ENDPOINT | cut -d':' -f1)
PORT=$(echo $ENDPOINT | cut -d':' -f2)

# Korekta długości klucza (wymagane 44 znaki Base64)
[ ${#PRIV_KEY} -eq 43 ] && PRIV_KEY="${PRIV_KEY}="
[ ${#PUB_KEY} -eq 43 ] && PUB_KEY="${PUB_KEY}="

echo "Podmieniam kraj na: $(basename $FILE)"

# 3. CZYSZCZENIE PLIKU KONFIGURACYJNEGO (Nuclear Option)
# Usuwamy wszystko od sekcji PROTON do końca pliku
sed -i '/config interface .PROTON./,$d' /etc/config/network
sed -i '/config wireguard_PROTON/,$d' /etc/config/network
sed -i '/config route .vpn_route_proton./,$d' /etc/config/network

# Usuwamy zbędne puste linie na końcu
sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' /etc/config/network

# 4. DOPISYWANIE NOWEJ KONFIGURACJI
cat << EOT >> /etc/config/network

config interface 'PROTON'
    option proto 'wireguard'
    option private_key '$PRIV_KEY'
    option addresses '$ADDR'
    option mtu '1420'
    option delegate '0'

config wireguard_PROTON 'wireguard_PROTON'
    option public_key '$PUB_KEY'
    option endpoint_host '$HOST'
    option endpoint_port '$PORT'
    option allowed_ips '0.0.0.0/0'
    option persistent_keepalive '25'
    option route_allowed_ips '0'

config route 'vpn_route_proton'
    option interface 'PROTON'
    option target '0.0.0.0'
    option netmask '0.0.0.0'
    option table '200'
EOT

# 5. MIĘKKIE PRZEŁADOWANIE (Bez restartu całego routera)
echo "Przeładowuję konfigurację..."
reload_config
sleep 2
ifup PROTON

# 6. CZEKANIE NA HANDSHAKE (Max 15s)
COUNT=0
while [ $COUNT -lt 15 ]; do
    if wg show PROTON 2>/dev/null | grep -q "latest handshake"; then
        echo "Handshake OK! Aktywuję routing..."
        sleep 2
        /root/toggle-vpn on
        exit 0
    fi
    echo "Czekam na połączenie... ($COUNT/15)"
    sleep 1
    COUNT=$((COUNT + 1))
done

echo "BŁĄD: VPN nie wstał. Sprawdź plik .conf lub klucze."
exit 1