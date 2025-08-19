SHELL := /bin/bash

.PHONY: setup test up down health e2e transcribe schedule

setup:
	./setup.sh

test:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	python3 -m pytest -q

up:
	docker compose up -d qdrant

down:
	docker compose down

health:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	python3 chat.py --health

e2e:
	@if [ -d .venv ]; then source .venv/bin/activate; elif [ -d venv ]; then source venv/bin/activate; fi; \
	docker compose up -d qdrant; \
	for i in $$(seq 1 30); do \
	  if curl -fsS http://localhost:6333/readyz /dev/null; then echo "Qdrant ready"; break; fi; \
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

