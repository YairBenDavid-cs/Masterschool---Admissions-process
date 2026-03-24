"""Shared pytest fixtures for the Masterschool Admissions Engine test suite."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.repository.in_memory import InMemoryUserRepository, get_repo
from app.core.config_models import FlowConfig, StepBlueprint, TaskBlueprint, TransitionRule, Status, PassConditionType
from app.core.config import load_flow_config, Settings


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
    return load_flow_config(Settings())
