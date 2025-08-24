# AI Agents Stack

[![CI](https://github.com/KoooD8/vesna/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/KoooD8/vesna/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/KoooD8/vesna?display_name=tag&sort=semver)](https://github.com/KoooD8/vesna/releases)
[![GHCR](https://img.shields.io/badge/GHCR-vesna-blue)](https://github.com/users/koood8/packages/container/package/vesna)

Назначение
- Web Research Agent: выполняет поиск через DuckDuckGo, Reddit и Google News RSS.
- Интеграция с Obsidian Vault: сохраняет результаты в папки Sources/ и Index/.
- Векторное хранилище на Qdrant: индексация и поиск по заметкам/результатам.

Структура
- chat.py: CLI/интерактив для поиска и сохранения результатов.
- agents/web_research/working_agent.py: основной агент.
- ingest.py: конвейер инжеста из Obsidian в Qdrant.
- vector_store.py: обертка над Qdrant и SentenceTransformers.
- setup.sh / run.sh: установка и запуск.
- ai.py: единый CLI-агрегатор команд.

Быстрый старт (ai CLI)
- Примеры:
  - ai health
  - ai search web "your query" --save
  - ai summarize topk "your query" --k 10 --title "TopK"
  - ai agent run --config configs/agents/core.yaml --id core.transcribe
  - ai schedule start --agents configs/agents/core.yaml --timezone Europe/Kyiv
  - ai docker up | up-all | down | logs | health
  - ai config show | ai config init --vault /path/to/Obsidian
  - Управление агентами:
    - ai agents list --file configs/agents/core.yaml --next --timezone Europe/Kyiv
    - ai agents enable --id core.transcribe --file configs/agents/core.yaml
    - ai agents disable --id core.transcribe --file configs/agents/core.yaml
    - ai agents new --id my.new.agent --file configs/agents/my.new.agent.yaml --schedule "0 9 * * *" --description "Daily morning run"
    - ai agents validate --file configs/agents/core.yaml
- Через Makefile:
  - make ai ARGS='health'
  - make ai ARGS='search web "your query" --save'
  - make ai ARGS='agents list --file configs/agents/core.yaml'

Установка
1) ./setup.sh
2) Поднимите Qdrant локально (например, Docker):
   docker run -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant

Опциональные компоненты
- Транскрибация (faster-whisper) вынесена в extras. Для установки:
  - macOS: сначала установите зависимости сборки для PyAV (используется faster-whisper):
    brew install pkg-config ffmpeg
  - затем:
    pip install -r requirements-extras.txt

Использование
- Запуск чата: ./run.sh
- Health-check основных сервисов (импорт агента, доступность Vault, Qdrant):
  python3 chat.py --health
- Веб-поиск и сохранение в Obsidian:
  python3 chat.py search:web "your query" --save
- Поиск новостей и сохранение в Obsidian:
  python3 chat.py search:news "your query" --save
- Индексация сохранённых JSON в Obsidian Index:
  python3 chat.py index:results path/to.json
- Сводка из файла результатов:
  python3 chat.py summarize:file path/to.json --title "My Summary"
- Векторный поиск и сохранение топ-K в Summaries:
  python3 chat.py summarize:topk "your query" --k 10

Пример pipeline-конфигурации и диагностика неизвестных шагов
- Минимальный пример: configs/agents/example.yaml
  Запуск:
    python3 -m orchestrator.cli --config configs/agents/example.yaml --print
- Смотрите также configs/agents/core.yaml. Если в pipeline указан неизвестный шаг, оркестратор выдаст:
  Unknown step: some_step. Available steps: create_daily_note, filter_results, health_check, ingest_qdrant, save_index, save_sources_markdown, search_web, transcribe_inbox, transcribe_inbox_whisper, vector_topk
- Это ускоряет отладку опечаток и несовпадений имён шагов.

Список доступных шагов из CLI
- Вы можете вывести список зарегистрированных шагов напрямую:
  python3 chat.py list-steps

Docker
- Сборка и запуск локально вместе с Qdrant:
  docker compose up --build
- Использование образа в compose: app тянет ghcr.io/koood8/vesna:v0.1.9 (multi-arch)
- Проверка здоровья приложения в контейнере (по умолчанию команда app — health):
  docker compose logs -f app
- Запуск произвольной команды внутри контейнера app:
  docker compose run --rm app python3 chat.py search:web "your query" --save

Публикация Docker-образа (GHCR)
- Multi-arch образ (linux/amd64, linux/arm64) публикуется автоматически.
- Быстрые команды:
  - docker pull ghcr.io/koood8/vesna:v0.1.9
  - docker run --rm ghcr.io/koood8/vesna:v0.1.9 python3 -c "import platform, sys, lxml; print(platform.machine()); print(sys.version); import lxml; print(lxml.__version__)"
  - Offline health-check (без сетевых загрузок моделей):
    docker run --rm -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_OFFLINE=1 ghcr.io/koood8/vesna:v0.1.9 python3 chat.py --health
- Образ публикуется в GitHub Container Registry при пушах в main и на теги v* через workflow .github/workflows/docker-publish.yml.
- Доступ к образу:
  - Если пакет публичный — docker pull ghcr.io/koood8/vesna:latest
  - Если приватный — выполните логин: echo "$GH_PAT" | docker login ghcr.io -u KoooD8 --password-stdin
- Права workflow: в Settings → Actions → General включите "Workflow permissions" → "Read and write permissions" (нужно для публикации в GHCR).
- Имена тегов:
  - latest — пуши в main
  - vX.Y.Z — создаются автоматически при тегах v*

Локальный деплой (без GHCR)
- Поднять Qdrant: docker compose --profile qdrant up -d
- Проверка стека:
  - make health (или python3 chat.py --health при активном venv)
- Сборка локального образа (по желанию):
  - docker build -t local/ai-agents-stack:latest .
- Полный стек через профили:
  - docker compose --profile all up -d --build

Инжест в Qdrant
- По умолчанию берёт Vault из
  /Users/onopriychukpavel/Library/Mobile Documents/iCloud~md~obsidian/Documents/Version1
- Примеры:
  python3 ingest.py --only-json
  python3 ingest.py --only-md
  python3 ingest.py --clear

Переменные окружения
- AI_STACK_QDRANT_URL (по умолчанию http://localhost:6333)
- AI_STACK_QDRANT_COLLECTION (по умолчанию ai_research)
- AI_STACK_EMB_MODEL (по умолчанию sentence-transformers/all-MiniLM-L6-v2)
- AI_STACK_CONFIG (путь к ai_agents_stack.config.yaml в Obsidian)
- AI_STACK_DEFAULT_VAULT (дефолтный путь к Obsidian Vault, если YAML отсутствует)
- AI_STACK_QDRANT_BATCH (размер батча upsert, по умолчанию 128)
- AI_STACK_HTTP_CACHE=1 (включить кэш HTTP) и AI_STACK_HTTP_CACHE_TTL (TTL в секундах)
- AI_STACK_RATE_INTERVAL (минимальный интервал между запросами в секундах)
- AI_STACK_JSON_LOGS=1 (включить JSON-логи)
- SERPAPI_KEY (включить выдачу через SerpAPI для DDG)
- REDDIT_CLIENT_ID и REDDIT_CLIENT_SECRET (OAuth для Reddit)
- OPENAI_API_KEY и/или ANTHROPIC_API_KEY (для LLM-суммаризации, опционально)

Загрузка .env
- Можно создать .env на основе .env.example. Переменные из .env будут подхвачены автоматически.

LLM-суммаризация (опционально)
- Установка LLM extras: pip install -r requirements-extras-llm.txt
- Пример команды: 
  python3 chat.py summarize:llm-file path/to.json --provider openai --model gpt-4o-mini --title "My LLM Summary"
- Поддерживаемые провайдеры: openai, anthropic (нужны ключи окружения)

YouTube/Telegram источники (без кода)
- Чтобы обработать YouTube через существующий шаг транскрибации, можно скачать аудио в Obsidian Inbox/Audio и затем запустить транскрибацию.
- Установка extras для источников: pip install -r requirements-extras-sources.txt
- Скачивание YouTube-аудио (список ссылок в urls.txt):
  scripts/fetch_youtube.sh urls.txt
- После загрузки файлов в Vault/Inbox/Audio запустите транскрибацию и инжест:
  python3 -m orchestrator.cli run-agent configs/agents/core.yaml
  или Makefile цель transcribe/e2e.
- Примечание: Telegram можно обрабатывать аналогично — сохраняйте аудио/видео в Inbox/Audio вручную или через сторонний клиент, затем используйте транскрибацию.

Extras и Torch
- Базовые зависимости не включают torch.
- Опциональные extras:
  - Транскрибация: pip install -r requirements-extras.txt (macOS: предварительно brew install pkg-config ffmpeg)
  - LLM: pip install -r requirements-extras-llm.txt
- Если требуется torch, используйте pinned версию (см. комментарии в requirements-extras.txt) и убедитесь в совместимости с вашей платформой.

Известные моменты/улучшения
- Безопасность GHCR: пакет публичный — не включайте секреты и приватные данные в образ. .env и локальные артефакты уже исключены из контекста. Для приватных настроек используйте переменные окружения при запуске.
- Reddit без официального API может отвечать 429/403. Добавлены ретраи и несколько запросов.
- DDG vqd токен может меняться — реализован fallback на HTML SERP.
- Для больших объёмов данных стоит добавить батчевую вставку в Qdrant и асинхронный пайплайн.

