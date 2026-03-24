"""
Integration tests for the Admissions Engine REST API endpoints and HATEOAS compliance.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.repository.in_memory import InMemoryUserRepository
from app.repository.in_memory import get_repo

client = TestClient(app)


# =============================================================================
# Test Environment Configuration
# =============================================================================

@pytest.fixture(autouse=True)
def fresh_repo():
    """
    Runs automatically before EVERY test.
    Overrides the FastAPI dependency to inject a fresh, empty repository,
    ensuring complete data isolation (preventing test pollution).
    """
    clean_repo = InMemoryUserRepository()
    app.dependency_overrides[get_repo] = lambda: clean_repo

    yield  # Test executes here

    app.dependency_overrides.clear()


# =============================================================================
# Helpers for Dynamic Discovery & Navigation
# =============================================================================

def get_flow_blueprint() -> dict:
    """
    Retrieves the full flow configuration from the API to avoid hardcoding names.

    Returns:
        dict: The parsed JSON response containing 'steps' and 'tasks_map'.
    """
    response = client.get("/api/v1/flow")
    assert response.status_code == 200, "Failed to fetch flow blueprint"
    return response.json()

def find_injection_task(blueprint: dict) -> tuple[str, str]:
    """
    Finds the first task and step that triggers a 'custom_flow' injection.

    Args:
        blueprint (dict): The full flow configuration as returned by the
            GET /flow endpoint.

    Returns:
        tuple[str, str]: A (step_name, task_id) pair for the first task
            with an inject_to_custom_flow transition, or (None, None)
            if no such task exists.
    """
    for step in blueprint["steps"]:
        for task_id in step["tasks"]:
            task_bp = blueprint.get("tasks_map", {}).get(task_id)
            if not task_bp:
                continue
            for transition in task_bp.get("transitions", []):
                if transition.get("inject_to_custom_flow"):
                    return step["name"], task_id
    return None, None

def get_multi_task_step(blueprint: dict) -> dict:
    """
    Finds the first step in the configuration that contains more than one task.

    Args:
        blueprint (dict): The full flow configuration as returned by the
            GET /flow endpoint.

    Returns:
        dict: The step dictionary containing 'name' and 'tasks', or None
            if no multi-task step exists.
    """
    for step in blueprint["steps"]:
        if len(step["tasks"]) > 1:
            return step
    return None

def navigate_to_step(
    user_id: str,
    target_step: str,
    current_user_data: dict,
    custom_payloads: dict = None
) -> dict:
    """
    Helper to dynamically advance a user to a specific step.

    Repeatedly submits task completions using the API-provided current_step
    and current_task until the user reaches the target step or a terminal
    state. Accepts an optional custom_payloads dict to override standard
    passing payloads for specific tasks.

    Args:
        user_id (str): The unique identifier of the user to advance.
        target_step (str): The name of the step to navigate toward.
        current_user_data (dict): The current API response containing
            the user's state (current_step, current_task, status).
        custom_payloads (dict): Optional mapping of task_name to payload
            dict, used to override the default passing payload for
            specific tasks.

    Returns:
        dict: The final API response after navigation completes, containing
            the user's updated state.
    """
    if custom_payloads is None:
        custom_payloads = {}

    user_data = current_user_data
    max_iterations = 20  # Circuit breaker to prevent infinite loops

    for _ in range(max_iterations):
        if user_data["current_step"] == target_step or user_data["status"] != "IN_PROGRESS":
            break

        current_task = user_data["current_task"]

        # Flex: Use custom payload if provided, otherwise fallback to generic passing values
        default_payload = {"score": 100, "decision": "passed_interview"}
        task_payload = custom_payloads.get(current_task, default_payload)

        payload = {
            "user_id": user_id,
            "step_name": user_data["current_step"],
            "task_name": current_task,
            "task_payload": task_payload
        }

        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Navigation failed at task '{current_task}'. Response: {res.text}"
        user_data = res.json()

    return user_data

def navigate_to_task(
    user_id: str,
    target_task: str,
    current_user_data: dict,
    custom_payloads: dict = None
) -> dict:
    """
    Advances a user through the flow until they reach a specific task name.

    Similar to navigate_to_step but stops at task granularity, allowing
    tests to target specific tasks within multi-task steps.

    Args:
        user_id (str): The unique identifier of the user to advance.
        target_task (str): The name of the task to navigate toward.
        current_user_data (dict): The current API response containing
            the user's state (current_step, current_task, status).
        custom_payloads (dict): Optional mapping of task_name to payload
            dict, used to override the default passing payload for
            specific tasks.

    Returns:
        dict: The final API response after navigation completes, containing
            the user's updated state.
    """
    if custom_payloads is None:
        custom_payloads = {}

    user_data = current_user_data
    max_iterations = 20  # Circuit breaker to prevent infinite loops

    for _ in range(max_iterations):
        if user_data["current_task"] == target_task or user_data["status"] != "IN_PROGRESS":
            break

        current_task = user_data["current_task"]

        default_payload = {"score": 100, "decision": "passed_interview"}
        task_payload = custom_payloads.get(current_task, default_payload)

        payload = {
            "user_id": user_id,
            "step_name": user_data["current_step"],
            "task_name": current_task,
            "task_payload": task_payload
        }

        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Navigation failed at task '{current_task}'. Response: {res.text}"
        user_data = res.json()

    return user_data


# =============================================================================
# 1. User Management & HATEOAS Discovery
# =============================================================================

def test_create_user_and_discover_start():
    """
    [Layer A] POST /users - Validates that a new user is placed in the FIRST step
    defined in the JSON, regardless of its name.

    Expected Behavior:
        The user is created at the first step/task from the flow blueprint,
        with HATEOAS links providing a PUT next_action.
    """
    # Arrange
    blueprint = get_flow_blueprint()
    expected_first_step = blueprint["steps"][0]["name"]
    expected_first_task = blueprint["steps"][0]["tasks"][0]

    # Act
    response = client.post("/api/v1/users", json={"email": "dynamic.candidate@test.com"})

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert "user_id" in data
    assert data["current_step"] == expected_first_step
    assert data["current_task"] == expected_first_task
    assert "_links" in data
    assert "next_action" in data["_links"]
    assert data["_links"]["next_action"]["method"] == "PUT"

def test_hateoas_progress_in_responses():
    """
    [Layer A] Validates that progress info (e.g., step index) is calculated correctly
    based on the blueprint and returned on state-changing actions (like POST).

    Expected Behavior:
        Progress contains current_step_index=1, total_steps matching the
        blueprint, and is_terminal=False for a newly created user.
    """
    # Arrange & Act
    response = client.post("/api/v1/users", json={"email": "progress@test.com"})

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert "progress" in data
    assert data["progress"]["current_step_index"] == 1
    assert data["progress"]["total_steps"] == len(get_flow_blueprint()["steps"])
    assert "is_terminal" in data["progress"]
    assert data["progress"]["is_terminal"] is False

def test_get_user_current_step_and_task():
    """
    [Layer A] GET /users/{id}/current - Validates the optimized endpoint returns
    ONLY the current step and task.

    Expected Behavior:
        Response contains current_step and current_task but NOT status,
        proving endpoint isolation.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "current@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/current")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "current_step" in data
    assert "current_task" in data
    assert "status" not in data  # Proving it is optimized/isolated

def test_get_user_overarching_status():
    """
    [Layer A] GET /users/{id}/status - Validates the optimized endpoint returns
    ONLY the overarching status (ACCEPTED, REJECTED, IN_PROGRESS).

    Expected Behavior:
        Response contains status but NOT current_step, proving endpoint isolation.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "status@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/status")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "current_step" not in data  # Proving it is optimized/isolated


# =============================================================================
# 2. Dynamic Logic & Step Navigation
# =============================================================================

def test_multi_task_step_persistence():
    """
    [Layer A] PUT /tasks/complete - Verifies that a user remains on the same 'current_step'
    if the step contains multiple tasks, until all tasks are completed.

    Expected Behavior:
        After completing the first task of a multi-task step, the user's
        current_step remains unchanged while current_task advances.
    """
    # Arrange
    blueprint = get_flow_blueprint()
    multi_task_step = get_multi_task_step(blueprint)

    if not multi_task_step:
        pytest.skip("No multi-task step found in current flow_config.json")

    target_step = multi_task_step["name"]
    first_task = multi_task_step["tasks"][0]
    second_task = multi_task_step["tasks"][1]

    initial_user = client.post("/api/v1/users", json={"email": "multitask@test.com"}).json()
    user_data = navigate_to_step(initial_user["user_id"], target_step, initial_user)

    # Act
    assert user_data["current_step"] == target_step
    assert user_data["current_task"] == first_task

    res = client.put("/api/v1/tasks/complete", json={
        "user_id": user_data["user_id"],
        "step_name": target_step,
        "task_name": first_task,
        "task_payload": {"interview_date": "2026-05-01"}
    })

    # Assert
    assert res.status_code == 200
    updated_data = res.json()
    assert updated_data["current_step"] == target_step
    assert updated_data["current_task"] == second_task

def test_dynamic_task_injection_edge_case():
    """
    [Layer A] PUT /tasks/complete - Verifies that any task marked with
    'inject_to_custom_flow' in the JSON correctly updates the user state.

    Expected Behavior:
        After submitting a payload that triggers injection, the user's
        custom_flow list contains the injected task and current_task
        matches the injected task.
    """
    # Arrange
    blueprint = get_flow_blueprint()
    step_name, task_name = find_injection_task(blueprint)

    if not step_name:
        pytest.skip("No injection task found in current flow_config.json")

    initial_user = client.post("/api/v1/users", json={"email": "edge.case@test.com"}).json()
    user_data = navigate_to_step(initial_user["user_id"], step_name, initial_user)

    # Act
    payload = {
        "user_id": user_data["user_id"],
        "step_name": step_name,
        "task_name": task_name,
        "task_payload": {"score": 65}
    }
    response = client.put("/api/v1/tasks/complete", json=payload)

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data["custom_flow"]) > 0
    assert data["current_task"] in data["custom_flow"]


# =============================================================================
# 3. Terminal States & Security Guards
# =============================================================================

def test_terminal_state_lock():
    """
    [Layer A] PUT /tasks/complete - Validates that once a user reaches a terminal state
    (ACCEPTED/REJECTED), they are locked and cannot process further tasks.

    Expected Behavior:
        After reaching terminal state, a subsequent task completion attempt
        returns 400 Bad Request with 'terminal state' in the detail message.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "terminal@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_step(user_id, "NON_EXISTENT_STEP_TO_FORCE_COMPLETION", initial_user)
    assert user_data["status"] in ["ACCEPTED", "REJECTED"], "User did not reach terminal state"

    # Act
    payload = {
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": user_data["current_task"],
        "task_payload": {}
    }
    response = client.put("/api/v1/tasks/complete", json=payload)

    # Assert
    assert response.status_code == 400
    assert "terminal state" in response.json()["detail"].lower()

def test_error_task_mismatch():
    """
    [Layer A] PUT /tasks/complete - Validates that submitting a mismatched step/task
    pair is rejected with a 400 error.

    Expected Behavior:
        The API returns 400 Bad Request with a detail message containing
        'mismatch', proving the anti-cheat guard clause is active.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "mismatch@test.com"}).json()["user_id"]

    # Act
    payload = {
        "user_id": user_id,
        "step_name": "hacked_step",
        "task_name": "hacked_task",
        "task_payload": {}
    }
    response = client.put("/api/v1/tasks/complete", json=payload)

    # Assert
    assert response.status_code == 400
    assert "mismatch" in response.json()["detail"].lower()

def test_error_user_not_found():
    """
    [Layer A] GET /users/{id}/status - Validates that requesting a non-existent user
    returns the correct error response.

    Expected Behavior:
        The API returns 404 Not Found for any invalid or non-existent
        user UUID.
    """
    # Arrange
    non_existent_user_id = "non-existent-uuid"

    # Act
    response = client.get(f"/api/v1/users/{non_existent_user_id}/status")

    # Assert
    assert response.status_code == 404


# =============================================================================
# 4. The Full Journey (HATEOAS Compliance)
# =============================================================================

def test_complete_flow_following_api_instructions():
    """
    [Layer A] End-to-End: This test simply 'follows' the current_task and current_step
    provided by the API until it reaches a terminal state, proving complete decoupling.

    Expected Behavior:
        The user reaches a terminal state (ACCEPTED or REJECTED) by
        following HATEOAS-driven navigation without any hardcoded step names.
    """
    # Arrange
    response = client.post("/api/v1/users", json={"email": "full.journey@test.com"})
    assert response.status_code == 201
    user_data = response.json()
    user_id = user_data["user_id"]

    # Act
    max_iterations = 20
    for _ in range(max_iterations):
        if user_data["status"] in ["ACCEPTED", "REJECTED"]:
            break

        payload = {
            "user_id": user_id,
            "step_name": user_data["current_step"],
            "task_name": user_data["current_task"],
            "task_payload": {"score": 100, "decision": "passed_interview"}
        }
        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Failed at step: {user_data['current_step']}"
        user_data = res.json()

    # Assert
    assert user_data["status"] in ["ACCEPTED", "REJECTED"]


# =============================================================================
# 5. LAYER B: BUSINESS LOGIC TESTS
# =============================================================================

def test_iq_test_high_score_advances_to_interview():
    """
    [Layer B] Validates that a high IQ score (>75) advances the user directly to interview.

    A score of 100 on the perform_iq_test task should bypass the second chance
    injection path entirely and move the user to schedule_interview with an
    empty custom_flow list.

    Expected Behavior:
        User lands on interview/schedule_interview with no custom_flow injection.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "high.iq@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial_user)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_iq_test",
        "task_payload": {"score": 100}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["current_step"] == "interview"
    assert data["current_task"] == "schedule_interview"
    assert len(data["custom_flow"]) == 0

def test_iq_test_medium_score_injects_second_chance():
    """
    [Layer B] Validates that a medium IQ score (60-75) injects the second_chance_iq task.

    A score of 65 triggers the inject_to_custom_flow rule, keeping the user
    on the iq_test step but moving them to the second_chance_iq task.

    Expected Behavior:
        User is on iq_test/second_chance_iq, and custom_flow contains 'second_chance_iq'.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "medium.iq@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial_user)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_iq_test",
        "task_payload": {"score": 65}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["current_step"] == "iq_test"
    assert data["current_task"] == "second_chance_iq"
    assert "second_chance_iq" in data["custom_flow"]

def test_iq_test_low_score_causes_rejection():
    """
    [Layer B] Validates that a low IQ score (<60) causes immediate rejection.

    A score of 30 fails all conditional rules and hits the DEFAULT transition,
    which sets status=REJECTED and moves to TERMINAL_REJECTED.

    Expected Behavior:
        User is REJECTED with no custom_flow injection.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "low.iq@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial_user)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_iq_test",
        "task_payload": {"score": 30}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"
    assert len(data["custom_flow"]) == 0

def test_second_chance_iq_high_score_advances_to_interview():
    """
    [Layer B] Validates that passing the second chance IQ test advances to interview.

    After being injected into second_chance_iq, scoring above 75 should
    advance the user to interview/schedule_interview.

    Expected Behavior:
        User moves from second_chance_iq to interview/schedule_interview.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "second.chance.pass@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial_user)

    # Act — Trigger second chance injection
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_iq_test",
        "task_payload": {"score": 65}
    })
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["current_task"] == "second_chance_iq"

    # Act — Pass the second chance
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "second_chance_iq",
        "task_payload": {"score": 100}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["current_step"] == "interview"

def test_second_chance_iq_fail_causes_rejection():
    """
    [Layer B] Validates that failing the second chance IQ test causes rejection.

    After being injected into second_chance_iq, scoring at or below 75
    triggers the DEFAULT rule, resulting in REJECTED status.

    Expected Behavior:
        User is REJECTED after failing the second chance IQ test.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "second.chance.fail@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial_user)

    # Act — Trigger second chance injection
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_iq_test",
        "task_payload": {"score": 65}
    })
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["current_task"] == "second_chance_iq"

    # Act — Fail the second chance
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "second_chance_iq",
        "task_payload": {"score": 30}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"

def test_interview_pass_decision_advances_to_sign_contract():
    """
    [Layer B] Validates that a passing interview decision advances to sign_contract.

    Submitting decision='passed_interview' on perform_interview should
    advance the user to sign_contract/upload_identification_document.

    Expected Behavior:
        User lands on sign_contract/upload_identification_document.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "interview.pass@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_interview", initial_user)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_interview",
        "task_payload": {"decision": "passed_interview"}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["current_step"] == "sign_contract"
    assert data["current_task"] == "upload_identification_document"

def test_interview_fail_decision_causes_rejection():
    """
    [Layer B] Validates that a failing interview decision causes rejection.

    Submitting any decision other than 'passed_interview' triggers the
    DEFAULT rule, resulting in REJECTED status.

    Expected Behavior:
        User is REJECTED after submitting decision='failed'.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "interview.fail@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_interview", initial_user)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["current_step"],
        "task_name": "perform_interview",
        "task_payload": {"decision": "failed"}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"

def test_register_duplicate_email_returns_400():
    """
    [Layer B] Validates that registering the same email twice returns 400 Bad Request.

    The API must enforce email uniqueness at the registration endpoint,
    returning a descriptive error message on duplicate attempts.

    Expected Behavior:
        First POST returns 201, second POST with same email returns 400
        with 'already registered' in the detail message.
    """
    # Arrange
    email = "duplicate@test.com"

    # Act
    first_response = client.post("/api/v1/users", json={"email": email})
    second_response = client.post("/api/v1/users", json={"email": email})

    # Assert
    assert first_response.status_code == 201
    assert second_response.status_code == 400
    assert "already registered" in second_response.json()["detail"].lower()

def test_hateoas_no_next_action_link_on_terminal_state():
    """
    [Layer A] Validates that HATEOAS links omit 'next_action' when user is in a terminal state.

    When a user has reached ACCEPTED or REJECTED, there are no further
    actions available. The _links object should contain 'self' but NOT
    'next_action', guiding the client to stop making action requests.

    Expected Behavior:
        Terminal user response contains _links with 'self' but without 'next_action'.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "terminal.links@test.com"}).json()
    user_id = initial_user["user_id"]

    # Act — Navigate to terminal state
    user_data = navigate_to_step(user_id, "NON_EXISTENT_STEP_TO_FORCE_COMPLETION", initial_user)

    # Assert
    assert user_data["status"] in ["ACCEPTED", "REJECTED"]
    assert "_links" in user_data
    assert "next_action" not in user_data["_links"]

def test_hateoas_is_terminal_flag_true_on_completion():
    """
    [Layer A] Validates that the is_terminal progress flag is True when user completes the flow.

    After reaching a terminal state (ACCEPTED or REJECTED), the progress
    object's is_terminal field must be True, allowing the frontend to
    render completion UI without checking status strings.

    Expected Behavior:
        Terminal user has progress.is_terminal=True and status is ACCEPTED or REJECTED.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "terminal.flag@test.com"}).json()
    user_id = initial_user["user_id"]

    # Act — Navigate to terminal state (full flow completion)
    user_data = navigate_to_step(user_id, "NON_EXISTENT_STEP_TO_FORCE_COMPLETION", initial_user)

    # Assert
    assert user_data["progress"]["is_terminal"] is True
    assert user_data["status"] in ["ACCEPTED", "REJECTED"]

def test_health_check_endpoint():
    """
    [Layer A] Validates the /health liveness probe endpoint.

    The health check is used by container orchestration tools to verify
    the application is running and responsive.

    Expected Behavior:
        GET /health returns 200 with {"status": "healthy"}.
    """
    # Arrange — No setup required

    # Act
    response = client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
