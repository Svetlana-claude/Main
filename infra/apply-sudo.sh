#!/bin/bash
# Применяет infra/sudo-allowed.list -> /etc/sudoers.d/010-mokeeva
#
# Запуск: sudo bash infra/apply-sudo.sh [--dry-run]
#
# Сгенерированный файл проверяется visudo перед установкой. Битый sudoers
# способен лишить доступа к sudo целиком, поэтому установка идёт только после
# успешной проверки, а прежняя версия сохраняется рядом.

set -euo pipefail

USER_NAME=mokeeva
LIST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sudo-allowed.list"
TARGET=/etc/sudoers.d/010-mokeeva
OLD=/etc/sudoers.d/010-mokeeva-nopasswd     # прежнее широкое правило NOPASSWD:ALL
DRY_RUN=${1:-}

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo bash $0" >&2
    exit 1
fi
if [ ! -f "$LIST" ]; then
    echo "не найден список: $LIST" >&2
    exit 1
fi

# ── Разбор списка по разделам ─────────────────────────────────────────
declare -a root_cmds=() postgres_cmds=()
section=""
lineno=0
while IFS= read -r line || [ -n "$line" ]; do
    lineno=$((lineno + 1))
    if [[ "$line" =~ ^#[[:space:]]*===[[:space:]]*([a-z]+)[[:space:]]*===  ]]; then
        section="${BASH_REMATCH[1]}"
        continue
    fi
    line="${line%%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

    if [[ "$line" != /* ]]; then
        echo "строка $lineno: команда должна начинаться с полного пути: $line" >&2
        exit 1
    fi
    case "$section" in
        root)     root_cmds+=("$line") ;;
        postgres) postgres_cmds+=("$line") ;;
        *) echo "строка $lineno: команда вне раздела (# === root === / # === postgres ===)" >&2
           exit 1 ;;
    esac
done < "$LIST"

if [ ${#root_cmds[@]} -eq 0 ] && [ ${#postgres_cmds[@]} -eq 0 ]; then
    echo "список пуст — отказываюсь ставить правило, которое ничего не разрешает" >&2
    exit 1
fi

# ── Сборка файла sudoers ──────────────────────────────────────────────
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
{
    echo "# Сгенерирован из infra/sudo-allowed.list — вручную не править."
    echo "# Правки вносятся в список и применяются: sudo bash infra/apply-sudo.sh"
    echo "# Дата генерации: $(date '+%d.%m.%Y %H:%M')"
    echo
    if [ ${#root_cmds[@]} -gt 0 ]; then
        printf 'Cmnd_Alias MOKEEVA_ROOT = '
        printf '%s' "${root_cmds[0]}"
        for cmd in "${root_cmds[@]:1}"; do printf ', \\\n    %s' "$cmd"; done
        printf '\n\n'
    fi
    if [ ${#postgres_cmds[@]} -gt 0 ]; then
        printf 'Cmnd_Alias MOKEEVA_PG = '
        printf '%s' "${postgres_cmds[0]}"
        for cmd in "${postgres_cmds[@]:1}"; do printf ', \\\n    %s' "$cmd"; done
        printf '\n\n'
    fi
    [ ${#root_cmds[@]}     -gt 0 ] && echo "$USER_NAME ALL=(root)     NOPASSWD: MOKEEVA_ROOT"
    [ ${#postgres_cmds[@]} -gt 0 ] && echo "$USER_NAME ALL=(postgres) NOPASSWD: MOKEEVA_PG"
} > "$TMP"

echo "Команд разрешено: root — ${#root_cmds[@]}, postgres — ${#postgres_cmds[@]}"

# ── Проверка синтаксиса ───────────────────────────────────────────────
if ! visudo -c -q -f "$TMP"; then
    echo "ОШИБКА: сгенерированный sudoers не проходит проверку. Ничего не менял." >&2
    exit 1
fi
echo "Проверка visudo: пройдена"

if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "--- что было бы установлено в $TARGET ---"
    cat "$TMP"
    exit 0
fi

# ── Установка ─────────────────────────────────────────────────────────
if [ -f "$TARGET" ]; then
    cp -p "$TARGET" "$TARGET.bak-$(date +%d%m%y-%H%M%S)"
fi
install -o root -g root -m 0440 "$TMP" "$TARGET"
echo "Установлено: $TARGET"

# Широкое правило NOPASSWD:ALL убирается последним — до этого момента
# доступ сохраняется, даже если что-то не заладилось выше
if [ -f "$OLD" ]; then
    mv "$OLD" "/root/010-mokeeva-nopasswd.removed-$(date +%d%m%y-%H%M%S)"
    echo "Прежнее правило NOPASSWD:ALL убрано (копия в /root)"
fi

visudo -c -q && echo "Итоговая конфигурация sudo корректна"
echo
echo "Готово. Полный root с паролем сохранён: mokeeva в группе sudo."
