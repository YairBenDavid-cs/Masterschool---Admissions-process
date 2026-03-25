"""Tests for the specific Masterschool domain requirements and business logic."""

import pytest
from typing import Any, Dict

from app.models.domain import User
from app.repository.in_memory import InMemoryUserRepository
from app.core.config_models import FlowConfig, StepBlueprint, TaskBlueprint, TransitionRule, Status, PassConditionType
from app.services.admissions import (
    create_new_user,
    process_task_completion,
    get_user_record,
    _update_custom_flow,
    EmailAlreadyExistsError,
    UserNotFoundError,
    TaskMismatchError,
    WorkflowStateError,
    ConfigurationError
)

# Spec-compliant payloads for real flow config tasks
_PD_PAYLOAD = {"first_name": "Test", "last_name": "User", "email": "test@example.com", "timestamp": 1700000000}
_IQ_PASS_PAYLOAD = {"score": 100, "test_id": "test-001", "timestamp": 1700000000}
_IQ_MEDIUM_PAYLOAD = {"score": 65, "test_id": "test-001", "timestamp": 1700000000}
_SCHEDULE_PAYLOAD = {"interview_date": "2025-01-01"}
_INTERVIEW_PASS_PAYLOAD = {"decision": "passed_interview", "interview_date": "2025-01-01", "interviewer_id": "int-001"}
_INTERVIEW_FAIL_PAYLOAD = {"decision": "failed_interview", "interview_date": "2025-01-01", "interviewer_id": "int-001"}


# BUSINESS LOGIC TESTS (Production flow_config.json)


def test_second_chance_iq_pass_advances_to_interview(
    mock_repo: InMemoryUserRepository,
    real_flow_config: FlowConfig
) -> None:
    """
    [Layer B] Validates the Second Chance IQ detour happy path through production config.

    A user who scores in the 60-75 range on the IQ test gets a second
    chance task injected. Scoring above 75 on the second chance advances
    them to the interview step, proving the full detour-and-recovery path.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        real_flow_config (FlowConfig): The production FSM configuration.

    Expected Behavior:
        After IQ score=65, user lands on second_chance_iq with custom_flow
        injection. After second_chance score=80, user advances to interview.
    """
    # Arrange — Create user at starting position
    user = create_new_user(email="second.chance@test.com", repo=mock_repo, flow=real_flow_config)
    assert user.step_name == "personal_details"
    assert user.task_name == "submit_personal_details"

    # Act — Complete personal_details (AUTO_PASS)
    user = process_task_completion(
        user_id=user.id, step_name="personal_details", task_name="submit_personal_details",
        payload=_PD_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )

    # Assert — Now on IQ test
    assert user.step_name == "iq_test"
    assert user.task_name == "perform_iq_test"

    # Act — Submit medium IQ score (triggers injection)
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="perform_iq_test",
        payload=_IQ_MEDIUM_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )

    # Assert — Second chance injected
    assert user.task_name == "second_chance_iq"
    assert "second_chance_iq" in user.custom_flow

    # Act — Submit high score on second chance
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="second_chance_iq",
        payload={"score": 80}, repo=mock_repo, flow=real_flow_config
    )

    # Assert — Advanced to interview
    assert user.step_name == "interview"
    assert user.task_name == "schedule_interview"

def test_second_chance_iq_fail_rejects_user(
    mock_repo: InMemoryUserRepository,
    real_flow_config: FlowConfig
) -> None:
    """
    [Layer B] Validates that failing the second chance IQ test results in rejection.

    A user who receives a second chance but scores at or below 75 on the
    retry hits the DEFAULT rule, which terminates with REJECTED status.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        real_flow_config (FlowConfig): The production FSM configuration.

    Expected Behavior:
        After second_chance score=40, user is REJECTED at TERMINAL_REJECTED.
    """
    # Arrange — Create user and advance to IQ test
    user = create_new_user(email="fail.second@test.com", repo=mock_repo, flow=real_flow_config)
    user = process_task_completion(
        user_id=user.id, step_name="personal_details", task_name="submit_personal_details",
        payload=_PD_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )

    # Act — Medium score triggers second chance
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="perform_iq_test",
        payload=_IQ_MEDIUM_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )
    assert user.task_name == "second_chance_iq"

    # Act — Fail the second chance
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="second_chance_iq",
        payload={"score": 40}, repo=mock_repo, flow=real_flow_config
    )

    # Assert
    assert user.status == Status.REJECTED
    assert user.step_name == "TERMINAL_REJECTED"

def test_interview_rejection_on_wrong_decision(
    mock_repo: InMemoryUserRepository,
    real_flow_config: FlowConfig
) -> None:
    """
    [Layer B] Validates that a non-passing interview decision results in rejection.

    The perform_interview task requires decision='passed_interview' to advance.
    Submitting decision='failed_interview' triggers the explicit rejection rule,
    resulting in REJECTED status.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        real_flow_config (FlowConfig): The production FSM configuration.

    Expected Behavior:
        Submitting decision='failed_interview' causes REJECTED status.
    """
    # Arrange — Create user and advance to perform_interview
    user = create_new_user(email="interview.fail@test.com", repo=mock_repo, flow=real_flow_config)
    user = process_task_completion(
        user_id=user.id, step_name="personal_details", task_name="submit_personal_details",
        payload=_PD_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="perform_iq_test",
        payload=_IQ_PASS_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )
    assert user.step_name == "interview"
    assert user.task_name == "schedule_interview"

    user = process_task_completion(
        user_id=user.id, step_name="interview", task_name="schedule_interview",
        payload=_SCHEDULE_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )
    assert user.task_name == "perform_interview"

    # Act — Submit failing interview decision
    user = process_task_completion(
        user_id=user.id, step_name="interview", task_name="perform_interview",
        payload=_INTERVIEW_FAIL_PAYLOAD, repo=mock_repo, flow=real_flow_config
    )

    # Assert
    assert user.status == Status.REJECTED
