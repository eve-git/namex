.PHONY: license
.PHONY: setup
.PHONY: ci cd
.PHONY: run

MKFILE_PATH:=$(abspath $(lastword $(MAKEFILE_LIST)))
CURRENT_ABS_DIR:=$(patsubst %/,%,$(dir $(MKFILE_PATH)))

PROJECT_NAME:=namex_pay
DOCKER_NAME:=namex-pay

#################################################################################
# COMMANDS -- Setup                                                             #
#################################################################################
setup: install ## Setup the project

clean: clean-build clean-pyc clean-test ## Clean the project
	rm -rf .venv/
	rm -rf poetry.lock

clean-build: ## Clean build files
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -fr {} +

clean-pyc: ## Clean cache files
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## clean test files
	find . -name '.pytest_cache' -exec rm -fr {} +
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/

update: ## Upgrade lock
	poetry update

install: clean ## Install python virtrual environment
	test -f .venv/bin/activate || python3.12 -m venv  $(CURRENT_ABS_DIR)/.venv ;\
	. .venv/bin/activate ;\
	pipx install poetry
	poetry install


#################################################################################
# COMMANDS - CI                                                                 #
#################################################################################
ci: pylint flake8 test ## CI flow

pylint: ## Linting with pylint
	. .venv/bin/activate && pylint --rcfile=setup.cfg src/$(PROJECT_NAME)

flake8: ## Linting with flake8 ## tests
	. .venv/bin/activate && flake8 src/$(PROJECT_NAME)

test: ## Unit testing
	. .venv/bin/activate && pytest

mac-cov: test ## Run the coverage report and display in a browser window (mac)
	@open -a "Google Chrome" htmlcov/index.html

#################################################################################
# COMMANDS - Local                                                              #
#################################################################################

run: ## Run the project in local
	. .venv/bin/activate && python3.12 -m flask run -p 5000

#################################################################################
# Self Documenting Commands                                                     #
#################################################################################
.PHONY: help

.DEFAULT_GOAL := help

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
