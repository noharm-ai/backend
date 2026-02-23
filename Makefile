.PHONY: test-setup test test-file test-cov db-start db-stop db-reset

COMPOSE = docker compose -f docker-compose.test.yml

## First-time setup: start Docker and load the database
test-setup:
	chmod +x scripts/setup-test-db.sh
	./scripts/setup-test-db.sh

## Run all tests
test:
	ENV=test python -m pytest

## Run a specific test file (usage: make test-file FILE=tests/test_drug.py)
test-file:
	ENV=test python -m pytest $(FILE) -v

## Run tests with coverage report
test-cov:
	ENV=test python -m pytest --cov=. --cov-report=html

## Start the database container (data preserved)
db-start:
	$(COMPOSE) start

## Stop the database container (data preserved)
db-stop:
	$(COMPOSE) stop

## Full reset: destroy volume and reload from scratch
db-reset:
	$(COMPOSE) down -v
	./scripts/setup-test-db.sh
