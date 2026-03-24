"""Tests for the specific Masterschool domain requirements and business logic."""

import pytest
from tests.utils_api import client, navigate_to_step, navigate_to_task


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
