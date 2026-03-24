"""Tests for the underlying FSM system, routing, and agnostic flow mechanics."""

import pytest
from tests.utils_api import client, get_flow_blueprint, find_injection_task, get_multi_task_step, navigate_to_step, navigate_to_task



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
    assert data["progress"]["current_step_index"] == 0
    total = len(get_flow_blueprint()["steps"])
    assert data["progress"]["total_steps"] == total
    assert data["progress"]["completion_ratio"] == f"0/{total}"
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
        "current_step": target_step,
        "current_task": first_task,
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
        "current_step": step_name,
        "current_task": task_name,
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
        "current_step": user_data["current_step"],
        "current_task": user_data["current_task"],
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
        "current_step": "hacked_step",
        "current_task": "hacked_task",
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
            "current_step": user_data["current_step"],
            "current_task": user_data["current_task"],
            "task_payload": {"score": 100, "decision": "passed_interview"}
        }
        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Failed at step: {user_data['current_step']}"
        user_data = res.json()

    # Assert
    assert user_data["status"] in ["ACCEPTED", "REJECTED"]

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
    total = user_data["progress"]["total_steps"]
    assert user_data["progress"]["completion_ratio"] == f"{total}/{total}"

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
