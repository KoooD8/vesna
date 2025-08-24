# Makefile helpers for AI Agents Stack

SHELL := /bin/bash

.PHONY: help ai setup up up-all down logs health test e2e transcribe schedule build-image push-image pull-image run-image

help:
	@echo "Targets:"
	@echo "  ai          - run unified CLI: make ai ARGS='health' or ARGS='search web \"q\" --save'"
	@echo "  install     - pip install -e . (adds 'ai' entry point)"
	@echo "  uninstall   - pip uninstall ai-agents-stack"
	@echo "  setup       - run setup.sh"
	@echo "  up          - start qdrant only (profile qdrant)"
	@echo "  up-all      - start full stack (app+qdrant) with build"
	@echo "  down        - stop all containers"
	@echo "  logs        - follow app logs"
	@echo "  health      - run chat.py --health locally (venv if present)"
	@echo "  test        - run pytest locally (venv if present)"
	@echo "  e2e         - minimal end-to-end: search -> ingest -> summarize"
	@echo "  transcribe  - run transcribe_inbox_whisper pipeline"
	@echo "  schedule    - run scheduler for agents list"
	@echo "  build-image - build Docker image (GHCR name inferred)"
	@echo "  push-image  - push image to GHCR"
	@echo "  pull-image  - pull image from GHCR"
	@echo "  run-image   - run health-check using GHCR image"

setup:
	./setup.sh

up:
	docker compose --profile qdrant up -d

up-all:
	docker compose --profile all up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

health:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	python3 chat.py --health

# Local test via venv
test:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	python3 -m pytest -q

# End-to-end smoke
 e2e:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	docker compose --profile qdrant up -d; \
	for i in $$(seq 1 30); do \
	  if curl -fsS http://localhost:6333/readyz >/dev/null 2>&1; then echo "Qdrant ready"; break; fi; \
	  sleep 1; \
	done; \
	python3 chat.py search:web "gpt-5 release date" --save; \
	python3 ingest.py --only-json --limit 50; \
	python3 chat.py summarize:topk "gpt-5 release date" --k 5 --title "GPT-5 TopK"

transcribe:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	python3 -c "import pipelines.steps"; \
	python3 -c 'from orchestrator.runner import run_agent; cfg={"id":"core.transcribe","pipeline":[{"step":"transcribe_inbox_whisper","with":{"inbox":"Inbox/Audio","ingest":true,"per_chunk_notes":true}}]}; print(run_agent(cfg))'

schedule:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	python3 scheduler.py --agents configs/agents/core.yaml

# Docker image build and push
IMAGE_NAME ?= $(shell git config --get remote.origin.url | sed -E 's#https?://github.com/##; s/\.git$$//' | tr 'A-Z' 'a-z')
IMAGE_NAME := ghcr.io/$(IMAGE_NAME):latest

build-image:
	docker build -t $(IMAGE_NAME) .

push-image:
	docker push $(IMAGE_NAME)

pull-image:
	docker pull $(IMAGE_NAME)

run-image:
	docker run --rm -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_OFFLINE=1 $(IMAGE_NAME) python3 chat.py --health

# Unified CLI via Make
ai:
	@if [ -n "$(ARGS)" ]; then \
	  python3 ai.py $(ARGS); \
	else \
	  echo "Usage: make ai ARGS='health' or ARGS='search web \"query\" --save'"; \
	fi

install:
	python3 -m pip install -e .

uninstall:
	python3 -m pip uninstall -y ai-agents-stack
