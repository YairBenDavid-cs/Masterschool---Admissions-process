# ==============================================================================
# Masterschool Admissions Engine — Developer Makefile
#
# Usage:
#   make run              — Build and start the API (http://localhost:8000)
#   make stop             — Stop and remove containers
#   make test             — Run the full test suite inside Docker (no local Python needed)
#   make test-unit        — Run only unit tests (fast, no HTTP stack)
#   make test-integration — Run only integration tests (system logic, routing, etc.)
#   make test-E2E         — Run only end-to-end journey tests
#   make coverage         — Run full suite with terminal coverage report
#   make clean            — Remove Python cache files
#   make run-portal       — Run the candidate portal Streamlit app in a temporary container
#   make run-explorer     — Run the API Explorer script in a temporary container
# ==============================================================================

.PHONY: run stop test test-unit test-integration test-E2E coverage clean

# Build the Docker image and start the API in the foreground.
# Swagger UI will be available at http://localhost:8000/docs
run:
	docker-compose up --build

# Stop and remove the running container(s).
stop:
	docker-compose down


# Run the candidate portal Streamlit app in a temporary container.
run-portal:
	docker-compose run --rm -p 8501:8501 \
		-e API_BASE_URL=http://admissions-api:8000 \
		admissions-api streamlit run scripts/candidate_portal.py

# Run the API Explorer script in a temporary container.
run-explorer:
	docker-compose run --rm -it \
	-e API_URL=http://admissions-api:8000 \
	admissions-api python scripts/api_explorer.py

# Run the full pytest suite inside a temporary Docker container.
# The image is built automatically if not already present.
# No local Python installation required.
test:
	docker-compose run --rm admissions-api pytest tests/ -v

# Run only unit tests (engine, config, service layer — no HTTP stack, very fast).
test-unit:
	docker-compose run --rm admissions-api pytest tests/unit/ -v

# Run only integration tests (system logic, routing, etc.)
test-integration:
	docker-compose run --rm admissions-api pytest tests/integration/ -v

# Run only end-to-end journey tests (full registration → ACCEPTED/REJECTED flow).
test-E2E:
	docker-compose run --rm admissions-api pytest tests/E2E/ -v

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


