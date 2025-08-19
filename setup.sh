#!/bin/bash

set -euo pipefail

echo "🚀 Установка AI Agents Stack"

# Выбираем Python: 3.11, если доступен, иначе системный python3
PYBIN="python3"
if command -v python3.11 >/dev/null 2>&1; then
  PYBIN="python3.11"
fi

# Создаем виртуальное окружение, если ещё нет
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
  "$PYBIN" -m venv .venv
fi

# Активируем venv или .venv
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
else
  echo "❌ Не удалось найти виртуальное окружение"
  exit 1
fi

# Обновляем pip и ставим зависимости
python -m pip install --upgrade pip
pip install -r requirements.txt

# Подсказки об опциональных компонентах
OS_NAME="$(uname -s || echo unknown)"
if [ "$OS_NAME" = "Darwin" ]; then
  NEED_PKG=""
  command -v pkg-config >/dev/null 2>&1 || NEED_PKG="yes"
  command -v ffmpeg >/dev/null 2>&1 || NEED_PKG="yes"
  if [ -n "$NEED_PKG" ]; then
    echo "ℹ️  Для установки опционального модуля транскрибации (faster-whisper) на macOS необходимо:" 
    echo "    brew install pkg-config ffmpeg"
  fi
fi

echo "ℹ️  Опциональные зависимости (транскрибация): pip install -r requirements-extras.txt"

echo "✅ Установка завершена!"
echo "Запустите: ./run.sh"
