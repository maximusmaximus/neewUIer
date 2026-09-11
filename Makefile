HUB := $(shell if [ -f hub/cinenode-hub.py ]; then echo hub/cinenode-hub.py; elif [ -f public/cinenode-hub.py ]; then echo public/cinenode-hub.py; fi)

.PHONY: check test python node hook lint

check:
	./scripts/check.sh

python:
	python3 -m pip install -q -r requirements-dev.txt
	python3 -m ruff check $(HUB) hub/tests
	python3 $(HUB) --self-test
	HUB_PATH=$(HUB) python3 -m pytest hub/tests -q --cov --cov-report=term-missing

node:
	npm run test:protocol
	npm run typecheck

lint:
	python3 -m ruff check $(HUB) hub/tests

hook:
	git config core.hooksPath .githooks
