#!/bin/sh

# === KONFIGURACJA ===
DATE_DIR=$(date +%Y-%m-%d)
WIN_TARGET="fear8@win"
# Ścieżka dla PowerShell (do tworzenia folderu)
WIN_PS_BASE="D:\@INSTALKI\!DRIVERS\!ROUTER"
# Ścieżka dla SCP (do wysyłki plików - musi mieć / na początku)
WIN_SCP_BASE="/D:/@INSTALKI/!DRIVERS/!ROUTER"

LOCAL_TMP="/tmp/backup_stage"
HOSTNAME=$(cat /proc/sys/kernel/hostname)
REMOTE_FOLDER="full_backup_${HOSTNAME}_${DATE_DIR}"

echo "===> START BACKUP: $HOSTNAME -> $REMOTE_FOLDER"

# 1. Przygotowanie folderu tymczasowego w RAM
rm -rf "$LOCAL_TMP" && mkdir -p "$LOCAL_TMP"

# 2. Backup konfiguracji (standardowy .tar.gz)
echo "-> Pakowanie konfiguracji..."
sysupgrade -b "$LOCAL_TMP/backup-config.tar.gz" >/dev/null

# 3. Lista zainstalowanych pakietów (żeby wiedzieć co doinstalować)
echo "-> Zrzucanie listy pakietów..."
if command -v apk >/dev/null; then
    apk info | sort > "$LOCAL_TMP/packages.txt"
else
    opkg list-installed | cut -d' ' -f1 | sort > "$LOCAL_TMP/packages.txt"
fi

# 4. Kopia wszystkich skryptów i ustawień (cały /etc i /root)
echo "-> Pakowanie /etc i /root..."
tar -czf "$LOCAL_TMP/scripts_and_root.tar.gz" /etc /root 2>/dev/null

# 5. Backup binarny MTD (Zrzuty partycji dla ratowania "cegły")
echo "-> Zrzucanie partycji MTD..."
cat /proc/mtd > "$LOCAL_TMP/mtd_layout.txt"
# Próbujemy zrzucić najważniejsze partycje (automatycznie wykryje co masz)
for part in uboot u-boot kernel ubi firmware firmware2; do
    DEV=$(grep "\"$part\"" /proc/mtd | cut -d: -f1)
    if [ -n "$DEV" ]; then
        echo "   Dumping $part ($DEV)..."
        dd if="/dev/${DEV}ro" of="$LOCAL_TMP/${DEV}_${part}.bin" bs=64k 2>/dev/null
    fi
done

# 6. TWORZENIE FOLDERU NA WINDOWS (PowerShell jest odporny na błędy składni)
echo "-> Tworzenie folderu na Windows..."
ssh $WIN_TARGET "powershell -Command \"if (!(Test-Path '$WIN_PS_BASE\\$REMOTE_FOLDER')) { New-Item -ItemType Directory -Path '$WIN_PS_BASE\\$REMOTE_FOLDER' -Force }\""

# 7. WYSYŁKA PLIKÓW PRZEZ SCP
echo "-> Wysyłanie plików..."
scp -i /root/.ssh/id_dropbear -r $LOCAL_TMP/* "$WIN_TARGET:$WIN_SCP_BASE/$REMOTE_FOLDER/"

# 8. Czyszczenie
rm -rf "$LOCAL_TMP"
echo "===> GOTOWE! Sprawdź folder: $WIN_PS_BASE\\$REMOTE_FOLDER"
