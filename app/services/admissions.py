"""
Service layer orchestrating admissions workflow operations and FSM state transitions.
"""

# Standard Library
import uuid
from typing import Any, Dict, List, Optional

# Local Application
from app.models.domain import User
from app.repository.base import UserRepository
from app.core.config_models import FlowConfig, Status, StepBlueprint, TransitionRule
from app.core.engine import evaluate_transition, EngineEvaluationError
from app.core.validator import validate_task_payload, PayloadValidationError  # re-exported below
from app.core.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Custom Service Exceptions
# =============================================================================

class UserNotFoundError(Exception):
    """Raised when a specific user ID cannot be found in the repository."""
    pass

class EmailAlreadyExistsError(Exception):
    """Raised when attempting to register an email that is already in use."""
    pass

class WorkflowStateError(Exception):
    """Raised when an action is performed on a user in a terminal state."""
    pass

class TaskMismatchError(Exception):
    """Raised when the submitted task does not align with the user's current FSM state."""
    pass

class ConfigurationError(Exception):
    """Raised when there is an inconsistency in the FSM configuration metadata."""
    pass

# Re-exported so callers only need to import from app.services.admissions
__all__ = [
    "PayloadValidationError",
    "UserNotFoundError",
    "EmailAlreadyExistsError",
    "WorkflowStateError",
    "TaskMismatchError",
    "ConfigurationError",
]


# =============================================================================
# Service Layer Logic
# =============================================================================

def create_new_user(email: str, repo: UserRepository, flow: FlowConfig) -> User:
    """
    Initializes a new applicant in the admissions system.

    Validates uniqueness and sets the starting point based on the flow configuration.

    Args:
        email (str): The candidate's email address.
        repo (UserRepository): The persistence layer interface.
        flow (FlowConfig): The validated FSM configuration.

    Returns:
        User: The newly created user entity.

    Raises:
        EmailAlreadyExistsError: If the email is already taken.
        ConfigurationError: If the flow has no default steps defined.
    """
    logger.debug(f"Service: Creating user for {email}")

    if repo.get_user_by_email(email):
        raise EmailAlreadyExistsError(f"Email {email} is already registered.")

    if not flow.default_steps:
        raise ConfigurationError("FSM configuration must have at least one default step.")

    first_step = flow.default_steps[0]

    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        current_step=first_step.name,
        current_task=first_step.tasks[0] if first_step.tasks else None,
        status=Status.IN_PROGRESS,
        custom_flow=[]
    )

    return repo.save_user(new_user)


def get_user_record(user_id: str, repo: UserRepository) -> User:
    """
    Retrieves a user's current state with strict existence enforcement.

    Args:
        user_id (str): The unique ID of the user.
        repo (UserRepository): The persistence layer interface.

    Returns:
        User: The user entity found.

    Raises:
        UserNotFoundError: If the user does not exist.
    """
    user = repo.get_user(user_id)
    if not user:
        raise UserNotFoundError(f"User with ID {user_id} not found.")
    return user


def process_task_completion(
    user_id: str,
    current_step: str,
    current_task: str,
    payload: Dict[str, Any],
    repo: UserRepository,
    flow: FlowConfig
) -> User:
    """
    Orchestrates the completion of a task and calculates the next state.

    This function enforces business rules, invokes the FSM Engine for decisions,
    and handles 'dynamic task injection' into the user's custom_flow based on
    explicit metadata flags in the configuration.

    Args:
        user_id (str): The user's ID.
        current_step (str): The step being submitted.
        current_task (str): The task being submitted.
        payload (Dict[str, Any]): The data associated with the completion.
        repo (UserRepository): Persistence layer.
        flow (FlowConfig): FSM blueprint.

    Returns:
        User: The updated user state.

    Raises:
        UserNotFoundError: If user is missing.
        WorkflowStateError: If user is already ACCEPTED/REJECTED.
        TaskMismatchError: If the user is submitting a task they aren't assigned to.
        ConfigurationError: If the task blueprint is missing or engine fails.
    """
    user = get_user_record(user_id, repo)

    # Guard Clause: Terminal state check
    if user.is_terminated():
        raise WorkflowStateError(f"User {user_id} is already in a terminal state: {user.status}")

    # Guard Clause: Anti-cheat / State synchronization
    if user.current_step != current_step or user.current_task != current_task:
        raise TaskMismatchError(
            f"State mismatch. User is on {user.current_step}/{user.current_task}, "
            f"but submitted {current_step}/{current_task}."
        )

    # Retrieve blueprint for the current task
    task_blueprint = flow.tasks_map.get(current_task)
    if not task_blueprint:
        raise ConfigurationError(f"Task blueprint '{current_task}' not found in configuration.")

    # Validate payload against the task's declared schema contract
    # PayloadValidationError propagates to the route layer → HTTP 422
    validate_task_payload(payload, task_blueprint)

    # 1. Evaluate Decision (The Engine)
    try:
        transition = evaluate_transition(task_blueprint, payload)
    except EngineEvaluationError as exc:
        logger.error(f"Engine failed to evaluate transition: {exc}")
        raise ConfigurationError("Decision engine failure.") from exc

    # 2. Apply State Change (capture last task before overwriting)
    user.last_completed_task = current_task
    user.current_step = transition.next_step
    user.current_task = transition.next_task

    if transition.mark_status:
        user.status = transition.mark_status

    # 3. Dynamic Task Injection (Approach 3: Data-Driven)
    # The logic is now explicit: if the rule says inject, we inject.
    _update_custom_flow(user, transition)

    return repo.save_user(user)


def _find_injection_trigger(injected_task_id: str, flow: FlowConfig) -> str | None:
    """
    Finds which task's transition injects the given task_id via inject_to_custom_flow.

    Args:
        injected_task_id (str): The ID of the dynamically injected task to locate.
        flow (FlowConfig): The FSM configuration to scan.

    Returns:
        str | None: The ID of the task that triggers injection, or None if not found.
    """
    for task_id, blueprint in flow.tasks_map.items():
        for rule in blueprint.transitions:
            if rule.inject_to_custom_flow and rule.next_task == injected_task_id:
                return task_id
    return None


def build_personalized_task_sequence(user: User, flow: FlowConfig) -> list[str]:
    """
    Builds the user's personalized ordered task list by merging the default flow
    with any dynamically injected tasks, inserted after their trigger task.

    Args:
        user (User): The user entity containing custom_flow.
        flow (FlowConfig): The FSM configuration defining default steps and tasks.

    Returns:
        list[str]: Ordered list of task IDs representing this user's unique path.
    """
    # Phase 1: Flatten default steps into ordered task list
    sequence: list[str] = []
    for step in flow.default_steps:
        sequence.extend(step.tasks)

    # Phase 2: Insert each custom_flow task after its trigger task
    for custom_task_id in user.custom_flow:
        trigger_id = _find_injection_trigger(custom_task_id, flow)
        if trigger_id and trigger_id in sequence:
            insert_pos = sequence.index(trigger_id) + 1
            sequence.insert(insert_pos, custom_task_id)
        else:
            sequence.append(custom_task_id)  # fallback: append at end

    return sequence


def get_user_flow(user_id: str, repo: UserRepository, flow: FlowConfig) -> tuple[User, list[str]]:
    """
    Retrieves a user and their personalized ordered task sequence.

    Args:
        user_id (str): The unique ID of the user.
        repo (UserRepository): The persistence layer interface.
        flow (FlowConfig): The FSM configuration.

    Returns:
        tuple[User, list[str]]: The user entity and their ordered task sequence.

    Raises:
        UserNotFoundError: If the user does not exist.
    """
    user = get_user_record(user_id, repo)
    sequence = build_personalized_task_sequence(user, flow)
    return user, sequence


def _update_custom_flow(user: User, transition: TransitionRule) -> None:
    """
    Handles the injection of dynamic tasks into the user's personal custom_flow list.

    This is triggered by the 'inject_to_custom_flow' flag in the transition rule,
    making the system truly flexible and configuration-driven.

    Args:
        user (User): The user entity whose custom_flow may be modified.
        transition (TransitionRule): The matched transition rule containing
            the injection flag and the next_task to potentially inject.

    Returns:
        None
    """
    if transition.inject_to_custom_flow and transition.next_task != "NONE":
        if transition.next_task not in user.custom_flow:
            user.custom_flow.append(transition.next_task)
            logger.info(
                f"Data-driven injection: Task '{transition.next_task}' added to user {user.id} "
                f"custom_flow."
            )
