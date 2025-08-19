#!/bin/bash

set -euo pipefail

echo "🤖 Запуск AI Agents Stack"

# Активируем виртуальное окружение
if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "⚠️  Виртуальное окружение не найдено. Продолжаем без него..."
fi

# Предупреждение, если не установлены зависимости
if ! python3 -c 'import requests, bs4, yaml' 2>/dev/null; then
  echo "ℹ️  Похоже, зависимости не установлены. Запустить ./setup.sh сейчас? [Y/n]"
  read -r ans
  if [ -z "${ans:-}" ] || [[ "$ans" =~ ^[Yy]$ ]]; then
    if [ -x "./setup.sh" ]; then
      ./setup.sh
    else
      echo "❌ Не найден setup.sh"
    fi
  else
    echo "ℹ️  Пропускаем установку зависимостей. Возможно, запуск завершится ошибкой."
  fi
fi

# Запускаем чат, пробрасывая аргументы
python3 chat.py "$@"
