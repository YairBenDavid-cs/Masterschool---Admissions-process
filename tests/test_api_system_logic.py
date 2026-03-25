"""Tests for the underlying FSM system, routing, and agnostic flow mechanics."""

import pytest
from tests.utils_api import (
    client,
    get_flow_blueprint,
    find_injection_task,
    get_multi_task_step,
    navigate_to_step,
    navigate_to_task,
    DEFAULT_TASK_PAYLOADS,
)



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
    assert data["step_name"] == expected_first_step
    assert data["task_name"] == expected_first_task
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
    blueprint = get_flow_blueprint()
    total_tasks = sum(len(step["tasks"]) for step in blueprint["steps"])
    assert data["progress"]["total_steps"] == total_tasks
    assert data["progress"]["completion_ratio"] == f"0/{total_tasks}"
    assert "is_terminal" in data["progress"]
    assert data["progress"]["is_terminal"] is False

def test_get_user_current_step_and_task():
    """
    [Layer A] GET /users/{id}/current - Validates the optimized endpoint returns
    ONLY the current step and task.

    Expected Behavior:
        Response contains step_name and task_name but NOT status,
        proving endpoint isolation.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "current@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/current")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "step_name" in data
    assert "task_name" in data
    assert "status" not in data  # Proving it is optimized/isolated

def test_get_user_overarching_status():
    """
    [Layer A] GET /users/{id}/status - Validates the optimized endpoint returns
    ONLY the overarching status (ACCEPTED, REJECTED, IN_PROGRESS).

    Expected Behavior:
        Response contains status but NOT step_name, proving endpoint isolation.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "status@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/status")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "step_name" not in data  # Proving it is optimized/isolated


# =============================================================================
# 2. Dynamic Logic & Step Navigation
# =============================================================================

def test_multi_task_step_persistence():
    """
    [Layer A] PUT /tasks/complete - Verifies that a user remains on the same 'step_name'
    if the step contains multiple tasks, until all tasks are completed.

    Expected Behavior:
        After completing the first task of a multi-task step, the user's
        step_name remains unchanged while task_name advances.
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
    assert user_data["step_name"] == target_step
    assert user_data["task_name"] == first_task

    res = client.put("/api/v1/tasks/complete", json={
        "user_id": user_data["user_id"],
        "step_name": target_step,
        "task_name": first_task,
        "task_payload": DEFAULT_TASK_PAYLOADS.get(first_task, {})
    })

    # Assert
    assert res.status_code == 200
    updated_data = res.json()
    assert updated_data["step_name"] == target_step
    assert updated_data["task_name"] == second_task

def test_dynamic_task_injection_edge_case():
    """
    [Layer A] PUT /tasks/complete - Verifies that any task marked with
    'inject_to_custom_flow' in the JSON correctly updates the user state.

    Expected Behavior:
        After submitting a payload that triggers injection, the user's
        custom_flow list contains the injected task and task_name
        matches the injected task.
    """
    # Arrange
    blueprint = get_flow_blueprint()
    step_name, task_name = find_injection_task(blueprint)

    if not step_name:
        pytest.skip("No injection task found in current flow_config.json")

    initial_user = client.post("/api/v1/users", json={"email": "edge.case@test.com"}).json()
    user_data = navigate_to_step(initial_user["user_id"], step_name, initial_user)

    # Act — score of 65 triggers injection (medium band: 60-75)
    payload = {
        "user_id": user_data["user_id"],
        "step_name": step_name,
        "task_name": task_name,
        "task_payload": {"score": 65, "test_id": "test-001", "timestamp": 1700000000}
    }
    response = client.put("/api/v1/tasks/complete", json=payload)

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data["custom_flow"]) > 0
    assert data["task_name"] in data["custom_flow"]


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
        "step_name": user_data["step_name"],
        "task_name": user_data["task_name"],
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
    # Arrange — valid UUID format, but no such user exists in the DB
    non_existent_user_id = "00000000-0000-0000-0000-000000000000"

    # Act
    response = client.get(f"/api/v1/users/{non_existent_user_id}/status")

    # Assert
    assert response.status_code == 404


# =============================================================================
# 4. The Full Journey (HATEOAS Compliance)
# =============================================================================

def test_complete_flow_following_api_instructions():
    """
    [Layer A] End-to-End: This test simply 'follows' the task_name and step_name
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

    # Act — follow task_name from the API response, using spec-compliant payloads
    max_iterations = 20
    for _ in range(max_iterations):
        if user_data["status"] in ["ACCEPTED", "REJECTED"]:
            break

        task_name = user_data["task_name"]
        task_payload = DEFAULT_TASK_PAYLOADS.get(task_name, {})

        payload = {
            "user_id": user_id,
            "step_name": user_data["step_name"],
            "task_name": task_name,
            "task_payload": task_payload,
        }
        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Failed at step: {user_data['step_name']}"
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


# =============================================================================
# 5. Personalized Flow Endpoint
# =============================================================================

def test_get_user_flow_not_found_returns_404():
    """
    [Layer A] GET /users/{id}/flow - Validates that a 404 is returned for an unknown user.

    Expected Behavior:
        A request for a non-existent user_id returns HTTP 404.
    """
    # Use a valid UUID format that doesn't exist in the DB
    response = client.get("/api/v1/users/00000000-0000-0000-0000-000000000000/flow")
    assert response.status_code == 404


def test_get_user_flow_returns_all_default_tasks():
    """
    [Layer A] GET /users/{id}/flow - Validates that a new user gets 8 default tasks
    in the correct order matching the flow blueprint.

    Expected Behavior:
        total_tasks == number of tasks across all default steps,
        tasks list contains all expected task IDs in correct order.
    """
    # Arrange
    blueprint = get_flow_blueprint()
    expected_task_ids = [task for step in blueprint["steps"] for task in step["tasks"]]
    user_id = client.post("/api/v1/users", json={"email": "flow.default@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["total_tasks"] == len(expected_task_ids)
    actual_task_ids = [t["task_id"] for t in data["tasks"]]
    assert actual_task_ids == expected_task_ids


def test_get_user_flow_first_task_is_current_rest_pending():
    """
    [Layer A] GET /users/{id}/flow - Validates state assignment for a new user.

    Expected Behavior:
        The first task has state CURRENT, all subsequent tasks are PENDING,
        and no tasks are COMPLETED for a brand-new user.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "flow.states@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert tasks[0]["state"] == "CURRENT"
    for task in tasks[1:]:
        assert task["state"] == "PENDING"


def test_get_user_flow_no_injected_tasks_by_default():
    """
    [Layer A] GET /users/{id}/flow - Validates that is_injected is False for all
    tasks in a default (non-injected) user's flow.

    Expected Behavior:
        All tasks have is_injected=False when no custom_flow tasks are present.
    """
    # Arrange
    user_id = client.post("/api/v1/users", json={"email": "flow.no_inject@test.com"}).json()["user_id"]

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    tasks = response.json()["tasks"]
    assert all(t["is_injected"] is False for t in tasks)


def test_get_user_flow_second_chance_injected_correctly():
    """
    [Layer A] GET /users/{id}/flow - Validates that after a score in the injection
    range, the second_chance task is present with is_injected=True and total_tasks increases.

    Expected Behavior:
        total_tasks == 9, second_chance_iq appears after perform_iq_test,
        is_injected=True for the injected task only.
    """
    # Arrange
    blueprint = get_flow_blueprint()
    injection_step, injection_task = find_injection_task(blueprint)
    if not injection_task:
        pytest.skip("No injection task found in current flow_config.json")

    default_total = sum(len(step["tasks"]) for step in blueprint["steps"])
    initial_user = client.post("/api/v1/users", json={"email": "flow.inject@test.com"}).json()
    user_id = initial_user["user_id"]

    # Navigate to the injection task and trigger injection with score 65
    user_data = navigate_to_task(user_id, injection_task, initial_user)
    res = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["step_name"],
        "task_name": injection_task,
        "task_payload": {"score": 65, "test_id": "test-001", "timestamp": 1700000000}
    })
    assert res.status_code == 200

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["total_tasks"] == default_total + 1

    task_ids = [t["task_id"] for t in data["tasks"]]
    injection_pos = task_ids.index(injection_task)

    # The injected task must appear immediately after the trigger task
    injected_items = [t for t in data["tasks"] if t["is_injected"] is True]
    assert len(injected_items) == 1
    assert task_ids.index(injected_items[0]["task_id"]) == injection_pos + 1


def test_get_user_flow_second_chance_task_is_current():
    """
    [Layer A] GET /users/{id}/flow - Validates that after injection, the injected task
    is CURRENT and all preceding tasks are COMPLETED.

    Expected Behavior:
        submit_personal_details → COMPLETED
        perform_iq_test → COMPLETED
        second_chance_iq → CURRENT
        All remaining tasks → PENDING
    """
    # Arrange
    blueprint = get_flow_blueprint()
    injection_step, injection_task = find_injection_task(blueprint)
    if not injection_task:
        pytest.skip("No injection task found in current flow_config.json")

    initial_user = client.post("/api/v1/users", json={"email": "flow.second_chance@test.com"}).json()
    user_id = initial_user["user_id"]

    user_data = navigate_to_task(user_id, injection_task, initial_user)
    client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["step_name"],
        "task_name": injection_task,
        "task_payload": {"score": 65, "test_id": "test-001", "timestamp": 1700000000}
    })

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    tasks = response.json()["tasks"]
    found_current = False
    for task in tasks:
        if task["state"] == "CURRENT":
            found_current = True
            assert task["is_injected"] is True
        elif not found_current:
            assert task["state"] == "COMPLETED"
        else:
            assert task["state"] == "PENDING"
    assert found_current, "Expected exactly one CURRENT task"


def test_get_user_flow_accepted_all_completed():
    """
    [Layer A] GET /users/{id}/flow - Validates that after completing the full flow
    (ACCEPTED), all tasks are marked COMPLETED.

    Expected Behavior:
        status=ACCEPTED and every task has state=COMPLETED.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "flow.accepted@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_step(user_id, "NON_EXISTENT_STEP_TO_FORCE_COMPLETION", initial_user)
    assert user_data["status"] == "ACCEPTED"

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ACCEPTED"
    assert all(t["state"] == "COMPLETED" for t in data["tasks"])


def test_get_user_flow_rejected_states_split_correctly():
    """
    [Layer A] GET /users/{id}/flow - Validates that after rejection, tasks before the
    rejection point are COMPLETED, the rejection task is FAILED, and subsequent tasks
    are PENDING.

    Expected Behavior:
        Tasks before the rejection point → COMPLETED
        The rejection-triggering task → FAILED
        Tasks after the rejection point → PENDING
        No CURRENT tasks (user is terminal)
    """
    # Arrange — Reject by failing IQ test (score < 60)
    blueprint = get_flow_blueprint()
    injection_step, injection_task = find_injection_task(blueprint)
    if not injection_task:
        pytest.skip("No injection task found in current flow_config.json")

    initial_user = client.post("/api/v1/users", json={"email": "flow.rejected@test.com"}).json()
    user_id = initial_user["user_id"]

    user_data = navigate_to_task(user_id, injection_task, initial_user)
    res = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "step_name": user_data["step_name"],
        "task_name": injection_task,
        "task_payload": {"score": 30, "test_id": "test-001", "timestamp": 1700000000}
    })
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"

    # Act
    response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"
    states = [t["state"] for t in data["tasks"]]
    assert "CURRENT" not in states
    assert "COMPLETED" in states
    assert "FAILED" in states
    assert "PENDING" in states
    # Ordering: COMPLETED... → FAILED (exactly once) → PENDING...
    seen_failed = False
    seen_pending = False
    for s in states:
        if s == "FAILED":
            assert not seen_pending, "FAILED task found after a PENDING task"
            seen_failed = True
        elif s == "PENDING":
            seen_pending = True
        elif s == "COMPLETED":
            assert not seen_failed, "COMPLETED task found after the FAILED task"


def test_get_user_flow_total_tasks_matches_progress_total_steps():
    """
    [Layer A] Validates that total_tasks in the flow endpoint equals total_steps in
    the progress object — both must reflect the same personalized count.

    Expected Behavior:
        UserFlowResponse.total_tasks == UserStatusResponse.progress.total_steps
        for the same user at any point in their journey.
    """
    # Arrange
    res = client.post("/api/v1/users", json={"email": "flow.sync@test.com"})
    user_id = res.json()["user_id"]
    progress_total = res.json()["progress"]["total_steps"]

    # Act
    flow_response = client.get(f"/api/v1/users/{user_id}/flow")

    # Assert
    assert flow_response.status_code == 200
    assert flow_response.json()["total_tasks"] == progress_total
