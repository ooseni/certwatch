PY    ?= python3
VENV  := .venv
BIN   := $(VENV)/bin

.PHONY: help venv lint format test validate build local invoke clean

help:  ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

venv: $(BIN)/activate  ## Create the virtualenv with dev tools

$(BIN)/activate: requirements-dev.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r requirements-dev.txt
	touch $(BIN)/activate

lint: venv  ## Lint Python (ruff) and the SAM template (cfn-lint)
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests
	$(BIN)/cfn-lint template.yaml

format: venv  ## Auto-format Python code
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

test: venv  ## Run unit tests
	$(BIN)/pytest -q

validate:  ## Validate the SAM template
	sam validate --lint

build: venv  ## Build the Lambda package into .aws-sam/
	PATH="$(abspath $(BIN)):$$PATH" sam build  # SAM needs a python3.14 with pip; the venv has one

local: build  ## Run the API locally on http://127.0.0.1:3000
	sam local start-api

invoke: build  ## Invoke the health function once with a sample event
	sam local invoke HealthFunction --event events/health.json

clean:  ## Remove build artefacts and the virtualenv
	rm -rf .aws-sam $(VENV) .pytest_cache .ruff_cache
