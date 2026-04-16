#!/bin/sh
# switch-provider.sh

CONF="/root/.vpn_provider"
NEW_PROV=$(echo $1 | tr '[:lower:]' '[:upper:]')

[ "$NEW_PROV" != "WARP" ] && [ "$NEW_PROV" != "PROTON" ] && echo "Użycie: $0 [WARP|PROTON]" && exit 1

# Pobierz aktualny tryb ZANIM zmienisz dostawcę
CURRENT_MODE="INACTIVE"
/sbin/ip rule show | grep -q "50:" && CURRENT_MODE="GLOBAL"
/sbin/ip rule show | grep -q "45:" && CURRENT_MODE="SELECTIVE"

echo "$NEW_PROV" > "$CONF"
echo "Dostawca ustawiony na: $NEW_PROV"

# Przeładuj tylko jeśli VPN był włączony
if [ "$CURRENT_MODE" = "GLOBAL" ]; then
    /root/toggle-vpn on
elif [ "$CURRENT_MODE" = "SELECTIVE" ]; then
    /root/toggle-vpn selective_on
fi