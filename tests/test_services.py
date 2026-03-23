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

@pytest.fixture
def mock_repo() -> InMemoryUserRepository:
    """Provides a fresh, empty repository for each test."""
    return InMemoryUserRepository()

@pytest.fixture
def mock_flow_config() -> FlowConfig:
    """
    Provides a minimal FSM configuration that mirrors the assignment's logic, 
    including an AUTO_PASS task and an EVALUATE_PAYLOAD task (IQ Test).
    """
    return FlowConfig(
        default_steps=[
            StepBlueprint(
                name="personal_details", 
                display_name="Personal Details", 
                tasks=["submit_details"]
            )
        ],
        tasks_map={
            "submit_details": TaskBlueprint(
                name="submit_details",
                pass_condition_type=PassConditionType.AUTO_PASS,
                transitions=[
                    TransitionRule(
                        condition="DEFAULT", 
                        next_step="iq_test", 
                        next_task="perform_iq"
                    )
                ]
            ),
            "perform_iq": TaskBlueprint(
                name="perform_iq",
                pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
                transitions=[
                    TransitionRule(
                        condition="payload.get('score', 0) > 75", 
                        next_step="interview", 
                        next_task="schedule_interview"
                    ),
                    TransitionRule(
                        condition="DEFAULT", 
                        next_step="TERMINAL_REJECTED", 
                        next_task="NONE",
                        mark_status=Status.REJECTED
                    )
                ]
            ),
            "second_chance_iq": TaskBlueprint(
                name="second_chance_iq",
                pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
                transitions=[
                    TransitionRule(
                        condition="payload.get('score', 0) > 75",
                        next_step="interview",
                        next_task="schedule_interview"
                    ),
                    TransitionRule(
                        condition="DEFAULT",
                        next_step="TERMINAL_REJECTED",
                        next_task="NONE",
                        mark_status=Status.REJECTED
                    )
                ]
            )
        }
    )

# --- Creation & Retrieval Tests ---

def test_create_new_user_success(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """Validates that a new user is created and placed at the first step."""
    email = "candidate@example.com"
    
    user = create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)
    
    assert user.email == email
    assert user.status == Status.IN_PROGRESS
    assert user.current_step == "personal_details"
    assert user.current_task == "submit_details"

def test_create_new_user_duplicate_email(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """Validates the guard clause preventing duplicate email registrations."""
    email = "candidate@example.com"
    create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)
    
    with pytest.raises(EmailAlreadyExistsError):
        create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

def test_get_user_record_success(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """Validates successful retrieval of an existing user."""
    created_user = create_new_user(email="test@test.com", repo=mock_repo, flow=mock_flow_config)
    
    fetched_user = get_user_record(user_id=created_user.id, repo=mock_repo)
    assert fetched_user.id == created_user.id
    assert fetched_user.email == "test@test.com"

def test_get_user_record_not_found(mock_repo: InMemoryUserRepository) -> None:
    """Validates that requesting a non-existent user raises the correct exception."""
    with pytest.raises(UserNotFoundError):
        get_user_record(user_id="fake_id", repo=mock_repo)

# --- Task Processing & Orchestration Tests ---

def test_process_task_completion_mismatch(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """Validates the anti-cheat guard clause: user must submit their current task."""
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
    """Validates that a REJECTED or ACCEPTED user cannot process new tasks."""
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
    """Validates that a missing task blueprint in the config raises an error."""
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)
    
    # Intentionally corrupt the config map in memory for the test
    del mock_flow_config.tasks_map["submit_details"]
    
    with pytest.raises(ConfigurationError):
        process_task_completion(
            user_id=user.id,
            step_name="personal_details",
            task_name="submit_details",
            payload={},
            repo=mock_repo,
            flow=mock_flow_config
        )

def test_process_task_completion_with_payload_evaluation(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    Validates end-to-end service orchestration: 
    Passing an AUTO_PASS task, then passing an EVALUATE_PAYLOAD task (IQ Test > 75).
    """
    # 1. Create User
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)
    
    # 2. Complete Step 1 (AUTO_PASS)
    updated_user = process_task_completion(
        user_id=user.id,
        step_name="personal_details",
        task_name="submit_details",
        payload={"first_name": "John"}, # Payload is ignored by engine for AUTO_PASS
        repo=mock_repo,
        flow=mock_flow_config
    )
    
    assert updated_user.current_step == "iq_test"
    assert updated_user.current_task == "perform_iq"

    # 3. Complete Step 2 (EVALUATE_PAYLOAD) with a passing score
    final_user = process_task_completion(
        user_id=updated_user.id,
        step_name="iq_test",
        task_name="perform_iq",
        payload={"score": 85}, # Score > 75, should go to interview
        repo=mock_repo,
        flow=mock_flow_config
    )
    
    assert final_user.current_step == "interview"
    assert final_user.current_task == "schedule_interview"
    assert final_user.status == Status.IN_PROGRESS

def test_process_task_completion_second_chance_edge_case(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    CRITICAL TEST: Validates the 'Second Chance' requirement.
    Checks if a medium score (60-75) updates current_task AND injects it into custom_flow.
    """
    # 1. Arrange: Update mock config to include the second chance rule with Explicit Injection Flag
    mock_flow_config.tasks_map["perform_iq"].transitions.insert(0, TransitionRule(
        condition="payload.get('score', 0) >= 60 and payload.get('score', 0) <= 75",
        next_step="iq_test",
        next_task="second_chance_iq",
        inject_to_custom_flow=True  # Approach 3: Data-Driven flag
    ))
    
    user = create_new_user(email="edge@case.com", repo=mock_repo, flow=mock_flow_config)
    # Move to IQ step first
    user.current_step = "iq_test"
    user.current_task = "perform_iq"
    mock_repo.save_user(user)

    # 2. Act: Submit a 'medium' score
    updated_user = process_task_completion(
        user_id=user.id,
        step_name="iq_test",
        task_name="perform_iq",
        payload={"score": 65},
        repo=mock_repo,
        flow=mock_flow_config
    )

    # 3. Assert
    assert updated_user.current_task == "second_chance_iq"
    # The second chance task should be injected into the custom_flow for tracking
    assert "second_chance_iq" in updated_user.custom_flow
    assert updated_user.status == Status.IN_PROGRESS

def test_process_task_completion_terminal_rejection(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """Validates that a low score correctly triggers a terminal REJECTED status."""
    user = create_new_user(email="fail@test.com", repo=mock_repo, flow=mock_flow_config)
    user.current_step = "iq_test"
    user.current_task = "perform_iq"
    mock_repo.save_user(user)

    # Act: Submit a failing score (triggers DEFAULT rule in mock_flow_config)
    final_user = process_task_completion(
        user_id=user.id,
        step_name="iq_test",
        task_name="perform_iq",
        payload={"score": 40},
        repo=mock_repo,
        flow=mock_flow_config
    )

    # Assert
    assert final_user.status == Status.REJECTED
    assert final_user.current_step == "TERMINAL_REJECTED"