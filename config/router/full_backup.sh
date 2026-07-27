#!/bin/sh
# full_backup.sh — pełny backup OpenWrt na FEAR-PC (Windows)
# Config + pakiety + /etc /root + partycje MTD (gzip w /tmp, wysyłka scp)
# Działa na ROUTER (ramips) i AP (ath79). POSIX sh / BusyBox ash.

# ============ KONFIGURACJA ============
WIN_TARGET="fear8@win"
WIN_PS_BASE="D:\\@INSTALKI\\!DRIVERS\\!ROUTER"       # dla PowerShell
WIN_SCP_BASE="/D:/@INSTALKI/!DRIVERS/!ROUTER"        # dla SCP
SSH_KEY="/root/.ssh/id_dropbear"
LOCAL_TMP="/tmp/backup_stage"
# ======================================

HOSTNAME=$(cat /proc/sys/kernel/hostname)
DATE=$(date +%F_%H%M)
REMOTE_FOLDER="full_backup_${HOSTNAME}_${DATE}"
FAILED=0

[ -f "$SSH_KEY" ] && SSH_OPTS="-i $SSH_KEY" || SSH_OPTS=""
WSSH="ssh $SSH_OPTS -y $WIN_TARGET"

log()  { echo "[$(date +%H:%M:%S)] $*"; }
fail() { echo "[BLAD] $*" >&2; FAILED=$((FAILED+1)); }

echo "===================================================="
echo " BACKUP: $HOSTNAME  ->  $WIN_TARGET:$WIN_SCP_BASE/$REMOTE_FOLDER"
echo "===================================================="

# --- 0. Kontrola wstepna ---
log "Sprawdzam polaczenie z FEAR-PC..."
if ! $WSSH "echo OK" >/dev/null 2>&1; then
    echo "[BLAD] FEAR-PC niedostepny (uspiony?). Wlacz PC i uruchom ponownie."
    exit 1
fi

log "RAM/tmp przed startem:"
free -m 2>/dev/null | head -2
df -h /tmp 2>/dev/null | grep -v "^Filesystem"

rm -rf "$LOCAL_TMP" && mkdir -p "$LOCAL_TMP"

# --- 1. Konfiguracja (sysupgrade) ---
log "Backup konfiguracji (sysupgrade -b)..."
if sysupgrade -b "$LOCAL_TMP/backup-config.tar.gz" >/dev/null 2>&1 \
   && gzip -t "$LOCAL_TMP/backup-config.tar.gz" 2>/dev/null; then
    log "   OK"
else
    fail "sysupgrade -b"
fi

# --- 2. Lista pakietow i metadane ---
log "Zrzucam liste pakietow i metadane..."
if command -v apk >/dev/null 2>&1; then
    apk info 2>/dev/null | sort > "$LOCAL_TMP/packages.txt"
    apk list --installed 2>/dev/null | sort > "$LOCAL_TMP/packages_full.txt"
else
    opkg list-installed 2>/dev/null | cut -d' ' -f1 | sort > "$LOCAL_TMP/packages.txt"
fi
[ -s "$LOCAL_TMP/packages.txt" ] || fail "lista pakietow pusta"

{
    echo "=== openwrt_release ==="; cat /etc/openwrt_release
    echo; echo "=== kernel ==="; uname -a
    echo; echo "=== board ==="; ubus call system board 2>/dev/null
    echo; echo "=== mtd ==="; cat /proc/mtd
    echo; echo "=== df ==="; df -h
    echo; echo "=== repozytoria ==="
    cat /etc/apk/repositories.d/* 2>/dev/null
    cat /etc/opkg/*.conf /etc/opkg/customfeeds.conf 2>/dev/null
} > "$LOCAL_TMP/system_info.txt"

cat /proc/mtd > "$LOCAL_TMP/mtd_layout.txt"

# --- 3. /etc i /root ---
log "Pakuje /etc i /root..."
if tar -czf "$LOCAL_TMP/scripts_and_root.tar.gz" /etc /root 2>/dev/null \
   && gzip -t "$LOCAL_TMP/scripts_and_root.tar.gz" 2>/dev/null; then
    log "   OK"
else
    fail "pakowanie /etc /root"
fi

# --- 4. Partycje MTD ---
# art/caldata/factory = kalibracja radiowa + MAC, NIE DO ODTWORZENIA z obrazu!
# Gzip w locie -> w /tmp laduja tylko skompresowane pliki (RAM-friendly na AP).
log "Zrzucam partycje MTD (gzip)..."
for part in u-boot uboot u-boot-env uboot-env bootloader \
            art caldata factory calibration \
            kernel rootfs ubi firmware firmware2 recovery; do
    DEV=$(grep "\"$part\"" /proc/mtd | cut -d: -f1)
    [ -n "$DEV" ] || continue

    SRC="/dev/${DEV}ro"; [ -e "$SRC" ] || SRC="/dev/$DEV"
    [ -e "$SRC" ] || { fail "brak urzadzenia dla $part"; continue; }

    SZ=$(grep "\"$part\"" /proc/mtd | awk '{print $2}')
    SZ_MB=$(( 0x$SZ / 1048576 ))
    log "   $part ($DEV, ~${SZ_MB} MB)"

    if dd if="$SRC" bs=64k 2>/dev/null | gzip -6 > "$LOCAL_TMP/${DEV}_${part}.bin.gz" \
       && gzip -t "$LOCAL_TMP/${DEV}_${part}.bin.gz" 2>/dev/null; then
        :
    else
        fail "$part — zrzut/kompresja nieudana"
    fi
done

# --- 5. Manifest (sha256 liczony lokalnie) ---
log "Generuje manifest (sha256)..."
( cd "$LOCAL_TMP" && sha256sum * > SHA256SUMS 2>/dev/null )
log "Rozmiar stage: $(du -sh "$LOCAL_TMP" | cut -f1)"

# --- 6. Folder na Windows ---
log "Tworze folder na Windows..."
if ! $WSSH "powershell -Command \"if (!(Test-Path '$WIN_PS_BASE\\$REMOTE_FOLDER')) { New-Item -ItemType Directory -Path '$WIN_PS_BASE\\$REMOTE_FOLDER' -Force | Out-Null }\""; then
    fail "tworzenie folderu na Windows"
    rm -rf "$LOCAL_TMP"
    exit 1
fi

# --- 7. Wysylka SCP ---
log "Wysylam pliki..."
if scp $SSH_OPTS -r "$LOCAL_TMP"/* "$WIN_TARGET:$WIN_SCP_BASE/$REMOTE_FOLDER/"; then
    log "   OK"
else
    fail "wysylka scp"
fi

# --- 8. Weryfikacja po stronie Windows (liczba plikow) ---
LOCAL_CNT=$(ls "$LOCAL_TMP" | wc -l)
REMOTE_CNT=$($WSSH "powershell -Command \"(Get-ChildItem '$WIN_PS_BASE\\$REMOTE_FOLDER').Count\"" 2>/dev/null | tr -d '\r ')
if [ "$LOCAL_CNT" = "$REMOTE_CNT" ]; then
    log "Weryfikacja: $REMOTE_CNT/$LOCAL_CNT plikow na miejscu"
else
    fail "weryfikacja: lokalnie $LOCAL_CNT, na Windows $REMOTE_CNT"
fi

# --- 9. Czyszczenie ---
rm -rf "$LOCAL_TMP"

echo "===================================================="
if [ "$FAILED" -eq 0 ]; then
    echo " GOTOWE — bez bledow"
else
    echo " ZAKONCZONO z $FAILED bledami — sprawdz powyzej!"
fi
echo " Lokalizacja: $WIN_PS_BASE\\$REMOTE_FOLDER"
echo "===================================================="
exit $FAILED