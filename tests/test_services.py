"""
Unit tests for the admissions service layer, validating FSM orchestration logic in isolation.
"""

import pytest
from typing import Any, Dict

from app.models.domain import User
from app.repository.in_memory import InMemoryUserRepository
from app.core.config_models import FlowConfig, StepBlueprint, TaskBlueprint, TransitionRule, Status, PassConditionType
from app.services.admissions import (
    create_new_user,
    process_task_completion,
    get_user_record,
    EmailAlreadyExistsError,
    UserNotFoundError,
    TaskMismatchError,
    WorkflowStateError,
    ConfigurationError
)

# =============================================================================
# FIXTURES (Decoupled & Isolated)
# =============================================================================

@pytest.fixture
def mock_repo() -> InMemoryUserRepository:
    """
    Provides a fresh, empty repository for each test.
    Ensures complete Data Isolation at the Service level without needing API overrides.
    """
    return InMemoryUserRepository()

@pytest.fixture
def mock_flow_config() -> FlowConfig:
    """
    Provides a generic FSM configuration for Service testing.
    Uses abstract names ('step_alpha', 'task_eval') to prove the Service
    is fully decoupled from the specific Masterschool business domain.
    """
    return FlowConfig(
        default_steps=[
            StepBlueprint(
                name="step_start",
                display_name="Start Step",
                tasks=["task_auto_pass"]
            ),
            StepBlueprint(
                name="step_evaluation",
                display_name="Evaluation Step",
                tasks=["task_eval"]
            )
        ],
        tasks_map={
            "task_auto_pass": TaskBlueprint(
                name="task_auto_pass",
                pass_condition_type=PassConditionType.AUTO_PASS,
                transitions=[
                    TransitionRule(
                        condition="DEFAULT",
                        next_step="step_evaluation",
                        next_task="task_eval"
                    )
                ]
            ),
            "task_eval": TaskBlueprint(
                name="task_eval",
                pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
                transitions=[
                    # 1. Standard Success
                    TransitionRule(
                        condition="payload.get('score', 0) > 80",
                        next_step="step_final",
                        next_task="task_final"
                    ),
                    # 2. Dynamic Injection (Approach 3) Edge Case
                    TransitionRule(
                        condition="payload.get('score', 0) >= 50 and payload.get('score', 0) <= 80",
                        next_step="step_evaluation",
                        next_task="task_injected_extra",
                        inject_to_custom_flow=True
                    ),
                    # 3. Default Rejection
                    TransitionRule(
                        condition="DEFAULT",
                        next_step="TERMINAL_REJECTED",
                        next_task="NONE",
                        mark_status=Status.REJECTED
                    )
                ]
            ),
            "task_injected_extra": TaskBlueprint(
                name="task_injected_extra",
                pass_condition_type=PassConditionType.AUTO_PASS,
                transitions=[
                    TransitionRule(
                        condition="DEFAULT",
                        next_step="step_final",
                        next_task="task_final"
                    )
                ]
            )
        }
    )

# =============================================================================
# 1. CREATION & RETRIEVAL TESTS
# =============================================================================

def test_create_new_user_success(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates that a new user is created and placed at the first step.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        The returned user has IN_PROGRESS status and is positioned at
        the first step and first task defined in the flow configuration.
    """
    email = "candidate@example.com"
    user = create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

    assert user.email == email
    assert user.status == Status.IN_PROGRESS
    assert user.current_step == "step_start"
    assert user.current_task == "task_auto_pass"

def test_create_new_user_duplicate_email(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates the guard clause preventing duplicate email registrations.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        The second registration attempt with the same email raises
        EmailAlreadyExistsError, leaving the repository unchanged.
    """
    email = "candidate@example.com"
    create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

    with pytest.raises(EmailAlreadyExistsError):
        create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

def test_get_user_record_success(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates successful retrieval of an existing user.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        The fetched user has the same ID as the originally created user.
    """
    created_user = create_new_user(email="test@test.com", repo=mock_repo, flow=mock_flow_config)

    fetched_user = get_user_record(user_id=created_user.id, repo=mock_repo)
    assert fetched_user.id == created_user.id

def test_get_user_record_not_found(mock_repo: InMemoryUserRepository) -> None:
    """
    Validates that requesting a non-existent user raises the correct exception.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.

    Expected Behavior:
        UserNotFoundError is raised when looking up a fake user ID.
    """
    with pytest.raises(UserNotFoundError):
        get_user_record(user_id="fake_id", repo=mock_repo)

# =============================================================================
# 2. GUARD CLAUSES & RESILIENCE TESTS
# =============================================================================

def test_process_task_completion_mismatch(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates the anti-cheat guard clause: user must submit their assigned task.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        TaskMismatchError is raised when the submitted step/task pair
        does not match the user's current FSM position.
    """
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)

    with pytest.raises(TaskMismatchError):
        process_task_completion(
            user_id=user.id,
            step_name="wrong_step",
            task_name="wrong_task",
            payload={},
            repo=mock_repo,
            flow=mock_flow_config
        )

def test_process_task_completion_already_terminal(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates that a user in a terminal state cannot process new tasks.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        WorkflowStateError is raised when attempting to complete a task
        for a user whose status is already REJECTED.
    """
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)
    user.status = Status.REJECTED
    mock_repo.save_user(user)

    with pytest.raises(WorkflowStateError):
        process_task_completion(
            user_id=user.id,
            step_name=user.current_step,
            task_name=user.current_task,
            payload={},
            repo=mock_repo,
            flow=mock_flow_config
        )

def test_process_task_completion_configuration_error(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates that missing task blueprints in the config crash safely with a custom error.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        ConfigurationError is raised when the task blueprint has been
        removed from the tasks_map, simulating a corrupted configuration.
    """
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)

    # Intentionally corrupt the config map in memory for the test
    del mock_flow_config.tasks_map["task_auto_pass"]

    with pytest.raises(ConfigurationError):
        process_task_completion(
            user_id=user.id,
            step_name="step_start",
            task_name="task_auto_pass",
            payload={},
            repo=mock_repo,
            flow=mock_flow_config
        )

# =============================================================================
# 3. DYNAMIC INJECTION & STATE MACHINE INTEGRITY
# =============================================================================

def test_process_task_completion_standard_flow(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates end-to-end service orchestration for a standard (Happy Path) user.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        Passing an AUTO_PASS task advances to step_evaluation, then a high
        score on the EVALUATE_PAYLOAD task advances to step_final with no
        custom_flow injection.
    """
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)

    # Complete Step 1 (AUTO_PASS)
    updated_user = process_task_completion(
        user_id=user.id, step_name="step_start", task_name="task_auto_pass",
        payload={}, repo=mock_repo, flow=mock_flow_config
    )
    assert updated_user.current_step == "step_evaluation"
    assert updated_user.current_task == "task_eval"

    # Complete Step 2 (High Score)
    final_user = process_task_completion(
        user_id=updated_user.id, step_name="step_evaluation", task_name="task_eval",
        payload={"score": 90}, repo=mock_repo, flow=mock_flow_config
    )
    assert final_user.current_step == "step_final"
    assert final_user.current_task == "task_final"
    assert final_user.status == Status.IN_PROGRESS
    assert len(final_user.custom_flow) == 0 # No injection occurred

def test_process_task_completion_dynamic_injection(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    CRITICAL TEST (Approach 3): Validates data-driven dynamic task injection.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration with
            an inject_to_custom_flow rule on the evaluation task.

    Expected Behavior:
        When the Engine triggers a rule with 'inject_to_custom_flow=True',
        the Service appends the new task to the user's custom_flow list
        and the user remains IN_PROGRESS.
    """
    user = create_new_user(email="edge@case.com", repo=mock_repo, flow=mock_flow_config)

    # Manually move to evaluation step for speed
    user.current_step = "step_evaluation"
    user.current_task = "task_eval"
    mock_repo.save_user(user)

    # Act: Submit a payload that triggers the injection rule (score: 60)
    updated_user = process_task_completion(
        user_id=user.id,
        step_name="step_evaluation",
        task_name="task_eval",
        payload={"score": 60},
        repo=mock_repo,
        flow=mock_flow_config
    )

    # Assert
    assert updated_user.current_task == "task_injected_extra"
    # Verify the Service successfully performed the dynamic injection
    assert "task_injected_extra" in updated_user.custom_flow
    assert updated_user.status == Status.IN_PROGRESS

def test_process_task_completion_terminal_rejection(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates that the Service correctly updates the User's terminal status based on Engine rules.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration with
            a DEFAULT rejection rule on the evaluation task.

    Expected Behavior:
        A failing score triggers the DEFAULT transition, setting the user
        status to REJECTED and moving them to TERMINAL_REJECTED.
    """
    user = create_new_user(email="fail@test.com", repo=mock_repo, flow=mock_flow_config)
    user.current_step = "step_evaluation"
    user.current_task = "task_eval"
    mock_repo.save_user(user)

    # Act: Submit a failing score to trigger the DEFAULT rule
    final_user = process_task_completion(
        user_id=user.id,
        step_name="step_evaluation",
        task_name="task_eval",
        payload={"score": 10},
        repo=mock_repo,
        flow=mock_flow_config
    )

    # Assert
    assert final_user.status == Status.REJECTED
    assert final_user.current_step == "TERMINAL_REJECTED"
