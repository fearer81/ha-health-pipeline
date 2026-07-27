#!/usr/bin/env bash
# gitexport — commit & push całego ha-project
set -euo pipefail
cd /root/ha-project

echo "=== git status ==="
git status --short

# Usuń z indeksu tylko to, co faktycznie łapie .gitignore (pliki zostają na dysku)
mapfile -t IGNORED < <(git ls-files -i -c --exclude-standard)
if (( ${#IGNORED[@]} )); then
    echo "=== usuwam z indeksu ${#IGNORED[@]} ignorowanych plików ==="
    printf '%s\n' "${IGNORED[@]}"
    git rm --cached --quiet -- "${IGNORED[@]}"
fi

git add -A

if git diff --cached --quiet; then
    echo "=== brak zmian do commitowania ==="
    exit 0
fi

# Bramka na sekrety — blokuje push, nie tylko ostrzega
echo "=== skan sekretów w staged ==="
PATTERN='ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|PrivateKey[[:space:]]*=|network_key|BEGIN [A-Z ]*PRIVATE KEY|rtsp://[^[:space:]/]*:[^[:space:]@]*@|password[[:space:]]*[:=][[:space:]]*[^[:space:]!]'
if git diff --cached -- . ':(exclude)gitexport.sh' | grep -nEi "$PATTERN"; then
    echo
    echo "!!! WYKRYTO POTENCJALNY SEKRET — push wstrzymany"
    echo "!!! popraw .gitignore albo użyj !secret, potem uruchom ponownie"
    exit 1
fi
echo "czysto"

git commit -m "Update $(date +%y%m%d-%H%M)"
git push

echo "=== gotowe ==="