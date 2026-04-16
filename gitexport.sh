#!/usr/bin/env bash
# gitexport — commit & push całego ha-project
set -euo pipefail

cd /root/ha-project

echo "=== git status ==="
git status

# Usuń z indeksu git to, co jest w .gitignore (bez usuwania z dysku), trzeba podać co
# git rm --cached config/hassio/*.log*

# Odkomentuj poniższe, by sprawdzić sekrety przed commitem:
# echo "=== sprawdzam sekrety w diff ==="
# git diff | grep -i -E "pass|token|key|secret"

git add .

# Odkomentuj, by podejrzeć staged zmiany:
# echo "=== diff staged ==="
# git diff --cached

git commit -m "Update"
git push

# Odkomentuj, by poszukać sekretów w całym repo:
# git grep -i -E "pass|token|secret"

echo "=== gotowe ==="
