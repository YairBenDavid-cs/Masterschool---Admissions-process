"""Tests for the specific Masterschool domain requirements and business logic."""

import pytest
from tests.utils_api import client, navigate_to_step, navigate_to_task, get_flow_blueprint


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
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
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
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
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
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
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
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
        "task_payload": {"score": 65}
    })
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["current_task"] == "second_chance_iq"

    # Act — Pass the second chance
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "current_step": user_data["current_step"],
        "current_task": "second_chance_iq",
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
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
        "task_payload": {"score": 65}
    })
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["current_task"] == "second_chance_iq"

    # Act — Fail the second chance
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "current_step": user_data["current_step"],
        "current_task": "second_chance_iq",
        "task_payload": {"score": 30}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"

def test_interview_pass_decision_advances_to_sign_contract():
    """
    [Layer B] Validates that a passing interview decision advances to sign_contract.

    Submitting decision='pass' on perform_interview should
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
        "current_step": user_data["current_step"],
        "current_task": "perform_interview",
        "task_payload": {"decision": "pass"}
    })

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["current_step"] == "sign_contract"
    assert data["current_task"] == "upload_identification_document"

def test_interview_fail_decision_causes_rejection():
    """
    [Layer B] Validates that a failing interview decision causes rejection.

    Submitting decision='fail' triggers the explicit rejection rule,
    resulting in REJECTED status.

    Expected Behavior:
        User is REJECTED after submitting decision='fail'.
    """
    # Arrange
    initial_user = client.post("/api/v1/users", json={"email": "interview.fail@test.com"}).json()
    user_id = initial_user["user_id"]
    user_data = navigate_to_task(user_id, "perform_interview", initial_user)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "current_step": user_data["current_step"],
        "current_task": "perform_interview",
        "task_payload": {"decision": "fail"}
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


# =============================================================================
# Payload Contract Validation Tests
# =============================================================================

def test_iq_test_missing_score_returns_422():
    """
    [Layer B] Validates that submitting an empty payload to perform_iq_test returns 422.

    The payload_schema in flow_config.json declares 'score' as required.
    Expected Behavior:
        PUT /tasks/complete with task_payload={} at iq_test step returns HTTP 422.
    """
    # Arrange — navigate to perform_iq_test
    initial = client.post("/api/v1/users", json={"email": "validation.missing@test.com"}).json()
    user_id = initial["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
        "task_payload": {}
    })

    # Assert
    assert response.status_code == 422
    assert "score" in response.json()["detail"]


def test_iq_test_wrong_type_score_returns_422():
    """
    [Layer B] Validates that submitting score as a string instead of int returns 422.

    The payload_schema declares 'score' as type 'int'.
    Expected Behavior:
        PUT /tasks/complete with task_payload={"score": "eighty"} returns HTTP 422.
    """
    # Arrange
    initial = client.post("/api/v1/users", json={"email": "validation.wrongtype@test.com"}).json()
    user_id = initial["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
        "task_payload": {"score": "eighty"}
    })

    # Assert
    assert response.status_code == 422
    assert "int" in response.json()["detail"]


def test_valid_payload_passes_validation():
    """
    [Layer B] Validates that a correctly-typed payload is not rejected — regression guard.

    Expected Behavior:
        PUT /tasks/complete with task_payload={"score": 90} returns HTTP 200.
    """
    # Arrange
    initial = client.post("/api/v1/users", json={"email": "validation.valid@test.com"}).json()
    user_id = initial["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial)

    # Act
    response = client.put("/api/v1/tasks/complete", json={
        "user_id": user_id,
        "current_step": user_data["current_step"],
        "current_task": "perform_iq_test",
        "task_payload": {"score": 90}
    })

    # Assert
    assert response.status_code == 200


def test_flow_blueprint_exposes_payload_schema():
    """
    [Layer B] Validates that GET /flow returns payload_schema for EVALUATE_PAYLOAD tasks.

    Expected Behavior:
        perform_iq_test entry in tasks_map contains a non-empty payload_schema
        with a field named 'score'.
    """
    # Act
    blueprint = get_flow_blueprint()

    # Assert
    iq_schema = blueprint["tasks_map"]["perform_iq_test"].get("payload_schema", [])
    assert len(iq_schema) > 0
    assert any(f["key_name"] == "score" for f in iq_schema)


def test_all_evaluate_payload_tasks_have_schema():
    """
    [Layer B] Dynamic contract coverage: every EVALUATE_PAYLOAD task defines payload_schema.

    This test automatically covers new tasks added to flow_config.json without
    requiring a new test case — zero-code-change coverage.

    Expected Behavior:
        Every task with pass_condition_type=EVALUATE_PAYLOAD has a non-empty payload_schema.
    """
    # Act
    blueprint = get_flow_blueprint()

    # Assert
    for task_id, task_bp in blueprint["tasks_map"].items():
        if task_bp["pass_condition_type"] == "EVALUATE_PAYLOAD":
            schema = task_bp.get("payload_schema", [])
            assert len(schema) > 0, (
                f"Task '{task_id}' is EVALUATE_PAYLOAD but has no payload_schema defined. "
                "Add a payload_schema to flow_config.json."
            )


# =============================================================================
# JIT Schema Discovery Tests
# =============================================================================

def test_user_status_response_includes_current_task_schema():
    """
    [Layer B] Validates that UserStatusResponse always contains current_task_schema.

    Expected Behavior:
        POST /users response includes a 'current_task_schema' field (may be empty
        for AUTO_PASS first task, but the key must always be present).
    """
    # Act
    response = client.post("/api/v1/users", json={"email": "jit.field_presence@test.com"})

    # Assert
    assert response.status_code == 201
    assert "current_task_schema" in response.json()


def test_current_task_schema_populated_for_evaluate_payload_task():
    """
    [Layer B] Validates that current_task_schema is non-empty when the user reaches
    an EVALUATE_PAYLOAD task (perform_iq_test).

    Expected Behavior:
        After advancing to perform_iq_test, current_task_schema contains a 'score'
        field with type 'int'.
    """
    # Arrange
    initial = client.post("/api/v1/users", json={"email": "jit.populated@test.com"}).json()
    user_id = initial["user_id"]

    # Act — advance to perform_iq_test and capture the response
    user_data = navigate_to_task(user_id, "perform_iq_test", initial)

    # Assert
    schema = user_data["current_task_schema"]
    assert len(schema) > 0
    assert any(f["key_name"] == "score" and f["value_type"] == "int" for f in schema)


def test_current_task_schema_empty_for_terminal_user():
    """
    [Layer B] Validates that a terminal user's response has an empty current_task_schema.

    Expected Behavior:
        After reaching ACCEPTED or REJECTED, the current_task_schema is an empty list.
    """
    # Arrange
    initial = client.post("/api/v1/users", json={"email": "jit.terminal@test.com"}).json()
    user_id = initial["user_id"]

    # Act — navigate to terminal state
    user_data = navigate_to_step(user_id, "NON_EXISTENT_STEP_TO_FORCE_COMPLETION", initial)

    # Assert
    assert user_data["status"] in ["ACCEPTED", "REJECTED"]
    assert user_data["current_task_schema"] == []


def test_current_task_schema_matches_flow_blueprint():
    """
    [Layer B] Validates consistency: current_task_schema in status response must match
    the payload_schema from the global flow blueprint for the same task.

    Expected Behavior:
        The schema served JIT in UserStatusResponse is identical to what GET /flow
        returns for the same task — no divergence between the two discovery paths.
    """
    # Arrange
    initial = client.post("/api/v1/users", json={"email": "jit.consistency@test.com"}).json()
    user_id = initial["user_id"]
    user_data = navigate_to_task(user_id, "perform_iq_test", initial)
    current_task = user_data["current_task"]

    # Act
    jit_schema = user_data["current_task_schema"]
    blueprint = get_flow_blueprint()
    blueprint_schema = blueprint["tasks_map"][current_task].get("payload_schema", [])

    # Assert — both paths must return identical schema
    assert jit_schema == blueprint_schema
