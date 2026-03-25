# ==============================================================================
# Masterschool Admissions Engine — Developer Makefile
#
# Usage:
#   make run       — Build and start the API (http://localhost:8000)
#   make stop      — Stop and remove containers
#   make test      — Run the full test suite inside Docker (no local Python needed)
#   make test-unit — Run only unit tests (fast, no HTTP stack)
#   make test-e2e  — Run only end-to-end journey tests
#   make coverage  — Run full suite with terminal coverage report
#   make clean     — Remove Python cache files
# ==============================================================================

.PHONY: run stop test test-unit test-e2e coverage clean

# Build the Docker image and start the API in the foreground.
# Swagger UI will be available at http://localhost:8000/docs
run:
	docker-compose up --build

# Stop and remove the running container(s).
stop:
	docker-compose down

# Run the full pytest suite inside a temporary Docker container.
# The image is built automatically if not already present.
# No local Python installation required.
test:
	docker-compose run --rm admissions-api pytest tests/ -v

# Run only unit tests (engine, config, service layer — no HTTP stack, very fast).
test-unit:
	docker-compose run --rm admissions-api pytest tests/unit/ -v

# Run only end-to-end journey tests (full registration → ACCEPTED/REJECTED flow).
test-e2e:
	docker-compose run --rm admissions-api pytest tests/e2e/ -v

# Run the full suite with a terminal coverage report.
# --cov=app        → measure coverage for the app/ package only (not tests themselves)
# --cov-report=term-missing → print a table showing which lines are NOT covered
coverage:
	docker-compose run --rm admissions-api pytest tests/ --cov=app --cov-report=term-missing

# Remove Python bytecode caches and pytest artefacts.
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
