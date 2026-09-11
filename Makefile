HUB := hub/cinenode-hub.py

.PHONY: check python node hook

check:
	./scripts/check.sh

python:
	python3 $(HUB) --self-test
	HUB_PATH=$(HUB) python3 -m pytest hub/tests -q

node:
	npm test
	npm run typecheck

hook:
	git config core.hooksPath .githooks
