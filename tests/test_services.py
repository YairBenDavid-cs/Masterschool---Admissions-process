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
    _update_custom_flow,
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

@pytest.fixture
def real_flow_config() -> FlowConfig:
    """
    Loads the actual production flow_config.json for Layer B business logic tests.

    Returns:
        FlowConfig: The validated production FSM configuration blueprint.
    """
    from app.core.config import load_flow_config, Settings
    return load_flow_config(Settings())

# =============================================================================
# 1. CREATION & RETRIEVAL TESTS
# =============================================================================

def test_create_new_user_success(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] Validates that a new user is created and placed at the first step.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        The returned user has IN_PROGRESS status and is positioned at
        the first step and first task defined in the flow configuration.
    """
    # Arrange
    email = "candidate@example.com"

    # Act
    user = create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

    # Assert
    assert user.email == email
    assert user.status == Status.IN_PROGRESS
    assert user.current_step == "step_start"
    assert user.current_task == "task_auto_pass"

def test_create_new_user_duplicate_email(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] Validates the guard clause preventing duplicate email registrations.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        The second registration attempt with the same email raises
        EmailAlreadyExistsError, leaving the repository unchanged.
    """
    # Arrange
    email = "candidate@example.com"
    create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

    # Act & Assert
    with pytest.raises(EmailAlreadyExistsError):
        create_new_user(email=email, repo=mock_repo, flow=mock_flow_config)

def test_get_user_record_success(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] Validates successful retrieval of an existing user.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        The fetched user has the same ID as the originally created user.
    """
    # Arrange
    created_user = create_new_user(email="test@test.com", repo=mock_repo, flow=mock_flow_config)

    # Act
    fetched_user = get_user_record(user_id=created_user.id, repo=mock_repo)

    # Assert
    assert fetched_user.id == created_user.id

def test_get_user_record_not_found(mock_repo: InMemoryUserRepository) -> None:
    """
    [Layer A] Validates that requesting a non-existent user raises the correct exception.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.

    Expected Behavior:
        UserNotFoundError is raised when looking up a fake user ID.
    """
    # Arrange
    fake_user_id = "fake_id"

    # Act & Assert
    with pytest.raises(UserNotFoundError):
        get_user_record(user_id=fake_user_id, repo=mock_repo)

# =============================================================================
# 2. GUARD CLAUSES & RESILIENCE TESTS
# =============================================================================

def test_process_task_completion_mismatch(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] Validates the anti-cheat guard clause: user must submit their assigned task.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        TaskMismatchError is raised when the submitted step/task pair
        does not match the user's current FSM position.
    """
    # Arrange
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)

    # Act & Assert
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
    [Layer A] Validates that a user in a terminal state cannot process new tasks.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        WorkflowStateError is raised when attempting to complete a task
        for a user whose status is already REJECTED.
    """
    # Arrange
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)
    user.status = Status.REJECTED
    mock_repo.save_user(user)

    # Act & Assert
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
    [Layer A] Validates that missing task blueprints in the config crash safely with a custom error.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        ConfigurationError is raised when the task blueprint has been
        removed from the tasks_map, simulating a corrupted configuration.
    """
    # Arrange
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)
    del mock_flow_config.tasks_map["task_auto_pass"]

    # Act & Assert
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
    [Layer A] Validates end-to-end service orchestration for a standard (Happy Path) user.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        Passing an AUTO_PASS task advances to step_evaluation, then a high
        score on the EVALUATE_PAYLOAD task advances to step_final with no
        custom_flow injection.
    """
    # Arrange
    user = create_new_user(email="test@example.com", repo=mock_repo, flow=mock_flow_config)

    # Act — Complete Step 1 (AUTO_PASS)
    updated_user = process_task_completion(
        user_id=user.id, step_name="step_start", task_name="task_auto_pass",
        payload={}, repo=mock_repo, flow=mock_flow_config
    )

    # Assert — Step 1
    assert updated_user.current_step == "step_evaluation"
    assert updated_user.current_task == "task_eval"

    # Act — Complete Step 2 (High Score)
    final_user = process_task_completion(
        user_id=updated_user.id, step_name="step_evaluation", task_name="task_eval",
        payload={"score": 90}, repo=mock_repo, flow=mock_flow_config
    )

    # Assert — Step 2
    assert final_user.current_step == "step_final"
    assert final_user.current_task == "task_final"
    assert final_user.status == Status.IN_PROGRESS
    assert len(final_user.custom_flow) == 0  # No injection occurred

def test_process_task_completion_dynamic_injection(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] CRITICAL TEST (Approach 3): Validates data-driven dynamic task injection.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration with
            an inject_to_custom_flow rule on the evaluation task.

    Expected Behavior:
        When the Engine triggers a rule with 'inject_to_custom_flow=True',
        the Service appends the new task to the user's custom_flow list
        and the user remains IN_PROGRESS.
    """
    # Arrange
    user = create_new_user(email="edge@case.com", repo=mock_repo, flow=mock_flow_config)
    user.current_step = "step_evaluation"
    user.current_task = "task_eval"
    mock_repo.save_user(user)

    # Act — Submit a payload that triggers the injection rule (score: 60)
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
    assert "task_injected_extra" in updated_user.custom_flow
    assert updated_user.status == Status.IN_PROGRESS

def test_process_task_completion_terminal_rejection(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] Validates that the Service correctly updates the User's terminal status based on Engine rules.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration with
            a DEFAULT rejection rule on the evaluation task.

    Expected Behavior:
        A failing score triggers the DEFAULT transition, setting the user
        status to REJECTED and moving them to TERMINAL_REJECTED.
    """
    # Arrange
    user = create_new_user(email="fail@test.com", repo=mock_repo, flow=mock_flow_config)
    user.current_step = "step_evaluation"
    user.current_task = "task_eval"
    mock_repo.save_user(user)

    # Act — Submit a failing score to trigger the DEFAULT rule
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

# =============================================================================
# 4. NEW GUARD CLAUSE & EDGE CASE TESTS
# =============================================================================

def test_create_new_user_empty_flow_raises(mock_repo: InMemoryUserRepository) -> None:
    """
    [Layer A] Validates that creating a user with an empty default_steps list raises ConfigurationError.

    The service must enforce that at least one step exists in the flow
    configuration before attempting to place a new user. An empty steps
    list indicates a misconfigured or incomplete FSM blueprint.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.

    Expected Behavior:
        ConfigurationError is raised when default_steps is an empty list,
        preventing user creation with no valid starting position.
    """
    # Arrange
    empty_flow = FlowConfig(
        default_steps=[],
        tasks_map={}
    )

    # Act & Assert
    with pytest.raises(ConfigurationError):
        create_new_user(email="empty@flow.com", repo=mock_repo, flow=empty_flow)

def test_update_custom_flow_idempotent() -> None:
    """
    [Layer A] Validates that _update_custom_flow is idempotent for duplicate injections.

    The custom_flow injection mechanism must prevent duplicate task entries.
    Calling _update_custom_flow twice with the same transition rule should
    result in exactly one entry in the user's custom_flow list, not two.

    Expected Behavior:
        After two identical injection calls, user.custom_flow contains
        exactly one entry for the injected task.
    """
    # Arrange
    user = User(
        id="idempotent-user",
        email="idempotent@test.com",
        current_step="step_eval",
        current_task="task_eval",
        status=Status.IN_PROGRESS,
        custom_flow=[]
    )
    transition = TransitionRule(
        condition="some_condition",
        next_step="step_eval",
        next_task="injected_task",
        inject_to_custom_flow=True
    )

    # Act — Call twice with the same transition
    _update_custom_flow(user, transition)
    _update_custom_flow(user, transition)

    # Assert — Only one entry despite two calls
    assert len(user.custom_flow) == 1
    assert user.custom_flow[0] == "injected_task"

def test_process_task_completion_extra_payload_fields(mock_repo: InMemoryUserRepository, mock_flow_config: FlowConfig) -> None:
    """
    [Layer A] Validates that extra unrelated fields in the payload do not cause errors.

    The engine evaluates only the fields referenced in the condition strings.
    Any additional fields in the payload should be silently ignored, ensuring
    forward compatibility with evolving webhook payloads.

    Args:
        mock_repo (InMemoryUserRepository): An empty in-memory repository.
        mock_flow_config (FlowConfig): A generic FSM configuration.

    Expected Behavior:
        A payload with extra fields (foo, irrelevant) alongside score=90
        processes normally, and the user advances to step_final.
    """
    # Arrange
    user = create_new_user(email="extra@fields.com", repo=mock_repo, flow=mock_flow_config)
    user.current_step = "step_evaluation"
    user.current_task = "task_eval"
    mock_repo.save_user(user)

    # Act
    updated_user = process_task_completion(
        user_id=user.id,
        step_name="step_evaluation",
        task_name="task_eval",
        payload={"score": 90, "foo": "bar", "irrelevant": 999},
        repo=mock_repo,
        flow=mock_flow_config
    )

    # Assert
    assert updated_user.current_step == "step_final"
    assert updated_user.current_task == "task_final"

# =============================================================================
# 5. LAYER B: BUSINESS LOGIC TESTS (Production flow_config.json)
# =============================================================================

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
    assert user.current_step == "personal_details"
    assert user.current_task == "submit_personal_details"

    # Act — Complete personal_details (AUTO_PASS)
    user = process_task_completion(
        user_id=user.id, step_name="personal_details", task_name="submit_personal_details",
        payload={}, repo=mock_repo, flow=real_flow_config
    )

    # Assert — Now on IQ test
    assert user.current_step == "iq_test"
    assert user.current_task == "perform_iq_test"

    # Act — Submit medium IQ score (triggers injection)
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="perform_iq_test",
        payload={"score": 65}, repo=mock_repo, flow=real_flow_config
    )

    # Assert — Second chance injected
    assert user.current_task == "second_chance_iq"
    assert "second_chance_iq" in user.custom_flow

    # Act — Submit high score on second chance
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="second_chance_iq",
        payload={"score": 80}, repo=mock_repo, flow=real_flow_config
    )

    # Assert — Advanced to interview
    assert user.current_step == "interview"
    assert user.current_task == "schedule_interview"

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
        payload={}, repo=mock_repo, flow=real_flow_config
    )

    # Act — Medium score triggers second chance
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="perform_iq_test",
        payload={"score": 65}, repo=mock_repo, flow=real_flow_config
    )
    assert user.current_task == "second_chance_iq"

    # Act — Fail the second chance
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="second_chance_iq",
        payload={"score": 40}, repo=mock_repo, flow=real_flow_config
    )

    # Assert
    assert user.status == Status.REJECTED
    assert user.current_step == "TERMINAL_REJECTED"

def test_interview_rejection_on_wrong_decision(
    mock_repo: InMemoryUserRepository,
    real_flow_config: FlowConfig
) -> None:
    """
    [Layer B] Validates that a non-passing interview decision results in rejection.

    The perform_interview task requires an exact string match of
    'passed_interview' to advance. Any other decision value triggers the
    DEFAULT rule, resulting in REJECTED status.

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
        payload={}, repo=mock_repo, flow=real_flow_config
    )
    user = process_task_completion(
        user_id=user.id, step_name="iq_test", task_name="perform_iq_test",
        payload={"score": 100}, repo=mock_repo, flow=real_flow_config
    )
    assert user.current_step == "interview"
    assert user.current_task == "schedule_interview"

    user = process_task_completion(
        user_id=user.id, step_name="interview", task_name="schedule_interview",
        payload={}, repo=mock_repo, flow=real_flow_config
    )
    assert user.current_task == "perform_interview"

    # Act — Submit failing interview decision
    user = process_task_completion(
        user_id=user.id, step_name="interview", task_name="perform_interview",
        payload={"decision": "failed_interview"}, repo=mock_repo, flow=real_flow_config
    )

    # Assert
    assert user.status == Status.REJECTED

def test_engine_is_completely_agnostic_to_domain() -> None:
    """
    [Layer A] Proves the FSM engine has zero coupling to the Masterschool domain.

    This test builds a completely fabricated 'Making Pizza' flow configuration
    inline (no JSON file) and runs it through the same service layer that
    powers the admissions engine. If this test passes, it proves that the
    engine, service, and repository are truly data-driven and domain-agnostic.

    Expected Behavior:
        A pizza with pineapple toppings is REJECTED; mushrooms are ACCEPTED.
        The engine applies arbitrary business rules purely from configuration.
    """
    # Arrange — Build a fabricated pizza-making flow
    pizza_flow = FlowConfig(
        default_steps=[
            StepBlueprint(name="dough_step", display_name="Prepare Dough", tasks=["prepare_dough"]),
            StepBlueprint(name="toppings_step", display_name="Add Toppings", tasks=["add_toppings"])
        ],
        tasks_map={
            "prepare_dough": TaskBlueprint(
                name="prepare_dough",
                pass_condition_type=PassConditionType.AUTO_PASS,
                transitions=[
                    TransitionRule(
                        condition="DEFAULT",
                        next_step="toppings_step",
                        next_task="add_toppings"
                    )
                ]
            ),
            "add_toppings": TaskBlueprint(
                name="add_toppings",
                pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
                transitions=[
                    TransitionRule(
                        condition="payload.get('toppings') == 'pineapple'",
                        next_step="TERMINAL_REJECTED",
                        next_task="NONE",
                        mark_status=Status.REJECTED
                    ),
                    TransitionRule(
                        condition="DEFAULT",
                        next_step="TERMINAL_ACCEPTED",
                        next_task="NONE",
                        mark_status=Status.ACCEPTED
                    )
                ]
            )
        }
    )
    pizza_repo = InMemoryUserRepository()

    # Act — Scenario 1: Pineapple pizza (should be rejected)
    pineapple_user = create_new_user(email="pineapple@pizza.com", repo=pizza_repo, flow=pizza_flow)
    assert pineapple_user.current_step == "dough_step"
    assert pineapple_user.current_task == "prepare_dough"

    pineapple_user = process_task_completion(
        user_id=pineapple_user.id, step_name="dough_step", task_name="prepare_dough",
        payload={}, repo=pizza_repo, flow=pizza_flow
    )
    assert pineapple_user.current_step == "toppings_step"
    assert pineapple_user.current_task == "add_toppings"

    pineapple_user = process_task_completion(
        user_id=pineapple_user.id, step_name="toppings_step", task_name="add_toppings",
        payload={"toppings": "pineapple"}, repo=pizza_repo, flow=pizza_flow
    )

    # Assert — Pineapple is rejected
    assert pineapple_user.status == Status.REJECTED

    # Act — Scenario 2: Mushroom pizza (should be accepted)
    mushroom_user = create_new_user(email="mushroom@pizza.com", repo=pizza_repo, flow=pizza_flow)
    mushroom_user = process_task_completion(
        user_id=mushroom_user.id, step_name="dough_step", task_name="prepare_dough",
        payload={}, repo=pizza_repo, flow=pizza_flow
    )
    mushroom_user = process_task_completion(
        user_id=mushroom_user.id, step_name="toppings_step", task_name="add_toppings",
        payload={"toppings": "mushrooms"}, repo=pizza_repo, flow=pizza_flow
    )

    # Assert — Mushrooms are accepted
    assert mushroom_user.status == Status.ACCEPTED
