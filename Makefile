PY    ?= python3
VENV  := .venv
BIN   := $(VENV)/bin

# LocalStack: dummy credentials, an explicit endpoint and no AWS_PROFILE, so the ls-* targets can
# never reach a real AWS account even when the default profile on this machine is a real one.
LS_STACK    := certwatch-local
LS_ENDPOINT := http://localhost.localstack.cloud:4566
LS_ENV      := env -u AWS_PROFILE AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
               AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_ENDPOINT_URL=$(LS_ENDPOINT)
LS_OUTPUT    = $(LS_ENV) aws cloudformation describe-stacks --stack-name $(LS_STACK) \
               --query "Stacks[0].Outputs[?OutputKey=='$(1)'].OutputValue" --output text

.PHONY: help venv lint format test validate build local invoke ls-up ls-down ls-deploy ls-test ls-destroy clean

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

local: build  ## Run the API on http://127.0.0.1:3000 (health only; /domains needs ls-deploy)
	$(LS_ENV) sam local start-api --warm-containers EAGER  # dummy credentials: sam local passes them into the containers

invoke: build  ## Invoke the health function once with a sample event
	$(LS_ENV) sam local invoke HealthFunction --event events/health.json

ls-up:  ## Start LocalStack and wait until it is ready
	localstack start -d
	localstack wait -t 120

ls-down:  ## Stop LocalStack (its state is discarded)
	localstack stop

ls-deploy: build  ## Deploy the stack to LocalStack
	$(LS_ENV) sam deploy --stack-name $(LS_STACK) --resolve-s3 --capabilities CAPABILITY_IAM \
		--parameter-overrides Stage=dev --no-confirm-changeset --no-fail-on-empty-changeset --no-progressbar
	@echo "API: $$($(call LS_OUTPUT,ApiUrl))"

ls-test: venv  ## Run the integration tests against the LocalStack deployment
	@url="$$($(call LS_OUTPUT,ApiUrl))"; table="$$($(call LS_OUTPUT,DomainsTableName))"; \
	test -n "$$url" -a "$$url" != None || { echo "no $(LS_STACK) stack on LocalStack; run make ls-deploy"; exit 1; }; \
	$(LS_ENV) CERTWATCH_API_URL="$$url" CERTWATCH_TABLE_NAME="$$table" $(BIN)/pytest -q -m integration

ls-destroy:  ## Delete the stack from LocalStack
	$(LS_ENV) sam delete --stack-name $(LS_STACK) --no-prompts

clean:  ## Remove build artefacts and the virtualenv
	rm -rf .aws-sam $(VENV) .pytest_cache .ruff_cache
