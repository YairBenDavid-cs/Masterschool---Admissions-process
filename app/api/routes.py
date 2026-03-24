"""
FastAPI route definitions for the Admissions Engine REST API.
"""

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

# Local Application — Domain & Config
from app.models.domain import User
from app.core.config_models import FlowConfig, Status

# Local Application — Schemas for request validation and response modeling
from app.models.schemas import (
    UserCreateRequest,
    UserStatusResponse,
    TaskCompleteRequest,
    FlowDefinitionResponse,
    ProgressInfo
)

# Local Application — Services & Exceptions
from app.services.admissions import (
    create_new_user,
    get_user_record,
    process_task_completion,
    UserNotFoundError,
    EmailAlreadyExistsError,
    WorkflowStateError,
    TaskMismatchError,
    ConfigurationError
)

# Local Application — Dependencies
from app.core.config import get_flow_config
from app.repository.in_memory import get_repo, UserRepository

router = APIRouter(prefix="/api/v1", tags=["Admissions Flow"])


# =============================================================================
# 1. POST - Create a user in the system
# =============================================================================

@router.post(
    "/users",
    response_model=UserStatusResponse,
    status_code=status.HTTP_201_CREATED
)
def register_user(
    request: UserCreateRequest,
    repo: UserRepository = Depends(get_repo),
    flow: FlowConfig = Depends(get_flow_config)
) -> UserStatusResponse:
    """
    Registers a new applicant and initiates their admissions workflow.

    Creates a new user entity in the repository and places them at the
    first step defined in the FSM flow configuration. Returns an enriched
    response with HATEOAS links guiding the client on available next actions.

    Args:
        request (UserCreateRequest): The incoming payload containing the
            applicant's email address.
        repo (UserRepository): The injected persistence layer dependency.
        flow (FlowConfig): The injected FSM configuration dependency.

    Returns:
        UserStatusResponse: The newly created user's state, enriched with
            progress info and HATEOAS navigation links.

    Raises:
        HTTPException: 400 Bad Request if the email is already registered.
    """
    try:
        user = create_new_user(email=request.email, repo=repo, flow=flow)
        return _build_user_response(user, flow)
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# =============================================================================
# 2. GET - Retrieve the entire flow
# =============================================================================

@router.get(
    "/flow",
    response_model=FlowDefinitionResponse,
    status_code=status.HTTP_200_OK
)
def get_flow(flow: FlowConfig = Depends(get_flow_config)) -> FlowDefinitionResponse:
    """
    Returns the full FSM blueprint including all steps and task definitions.

    Exposes the global flow configuration so the frontend can dynamically
    render the step map, progress indicators, and task metadata without
    hardcoding any domain knowledge.

    Args:
        flow (FlowConfig): The injected FSM configuration dependency.

    Returns:
        FlowDefinitionResponse: The complete flow definition containing
            ordered steps and the tasks map.
    """
    return FlowDefinitionResponse(
        steps=flow.default_steps,
        tasks_map=flow.tasks_map
    )


# =============================================================================
# 3. GET - Fetch the current step and task for a specific user
# =============================================================================

@router.get(
    "/users/{user_id}/current",
    response_model=Dict[str, str],
    status_code=status.HTTP_200_OK
)
def get_user_current_step_and_task(
    user_id: str,
    repo: UserRepository = Depends(get_repo)
) -> Dict[str, str]:
    """
    Returns only the current step and task for a specific user.

    A lightweight endpoint optimized for polling scenarios where the
    client only needs to know the user's position in the workflow,
    without the full enriched response payload.

    Args:
        user_id (str): The unique identifier of the user (path parameter).
        repo (UserRepository): The injected persistence layer dependency.

    Returns:
        Dict[str, str]: A dictionary containing 'current_step' and
            'current_task' keys.

    Raises:
        HTTPException: 404 Not Found if the user ID does not exist.
    """
    try:
        user = get_user_record(user_id=user_id, repo=repo)
        return {
            "current_step": user.current_step,
            "current_task": user.current_task
        }
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# =============================================================================
# 4. PUT - Mark a task as completed
# =============================================================================

@router.put(
    "/tasks/complete",
    response_model=UserStatusResponse,
    status_code=status.HTTP_200_OK
)
def complete_task(
    request: TaskCompleteRequest,
    repo: UserRepository = Depends(get_repo),
    flow: FlowConfig = Depends(get_flow_config)
) -> UserStatusResponse:
    """
    Orchestrates the completion of a task through the service layer.

    Delegates to the admissions service to validate the submission,
    evaluate FSM transitions via the engine, and apply state changes.
    Translates domain-specific exceptions into appropriate HTTP responses.

    Args:
        request (TaskCompleteRequest): The incoming payload containing
            user_id, step_name, task_name, and task_payload.
        repo (UserRepository): The injected persistence layer dependency.
        flow (FlowConfig): The injected FSM configuration dependency.

    Returns:
        UserStatusResponse: The updated user state after task completion,
            enriched with progress info and HATEOAS navigation links.

    Raises:
        HTTPException: 404 if the user is not found, 400 for workflow
            state or task mismatch errors, 500 for configuration errors.
    """
    try:
        user = process_task_completion(
            user_id=request.user_id,
            step_name=request.step_name,
            task_name=request.task_name,
            payload=request.task_payload,
            repo=repo,
            flow=flow
        )
        return _build_user_response(user, flow)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (WorkflowStateError, TaskMismatchError) as exc:
        # Client errors (400)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ConfigurationError as exc:
        # Server errors (500) - e.g., missing task in JSON
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# =============================================================================
# 5. GET - Check whether a user is accepted, rejected, or still in progress
# =============================================================================

@router.get(
    "/users/{user_id}/status",
    response_model=Dict[str, str],
    status_code=status.HTTP_200_OK
)
def get_user_status(
    user_id: str,
    repo: UserRepository = Depends(get_repo)
) -> Dict[str, str]:
    """
    Returns only the overarching admission status for a specific user.

    A lightweight endpoint that returns the user's high-level status
    (IN_PROGRESS, ACCEPTED, or REJECTED) without step or task details,
    optimized for dashboard polling and status badge rendering.

    Args:
        user_id (str): The unique identifier of the user (path parameter).
        repo (UserRepository): The injected persistence layer dependency.

    Returns:
        Dict[str, str]: A dictionary containing a single 'status' key.

    Raises:
        HTTPException: 404 Not Found if the user ID does not exist.
    """
    try:
        user = get_user_record(user_id=user_id, repo=repo)
        return {
            "status": user.status.value if hasattr(user.status, 'value') else user.status
        }
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _build_user_response(user: User, flow: FlowConfig) -> UserStatusResponse:
    """
    Enriches the domain User entity with HATEOAS-style links and progress tracking.

    Calculates the user's position within the flow, derives a completion
    percentage, and constructs navigational HATEOAS links that guide the
    client on what actions are available next.

    Args:
        user (User): The domain user entity containing current workflow state.
        flow (FlowConfig): The FSM configuration used to derive step ordering
            and total step count for progress calculations.

    Returns:
        UserStatusResponse: A fully enriched response DTO containing user
            state, progress info, and HATEOAS navigation links.
    """
    step_names = [step.name for step in flow.default_steps]
    total_steps = len(step_names)

    # 1. Progress Logic Fix
    is_terminal = user.status in [Status.ACCEPTED, Status.REJECTED]

    try:
        current_idx = step_names.index(user.current_step) + 1
        percentage = round((current_idx / total_steps) * 100, 2) if total_steps > 0 else 0.0
    except ValueError:
        # If step is not in default steps (e.g., TERMINAL_REJECTED)
        if user.status == Status.ACCEPTED:
            current_idx = total_steps
            percentage = 100.0
        else:
            # If rejected or unknown, don't pretend it's 100%.
            # We keep current_idx at 0 or a previous known state if we tracked it (simplified here).
            current_idx = 0
            percentage = 0.0

    progress_info = ProgressInfo(
        current_step_index=current_idx,
        total_steps=total_steps,
        percentage=percentage,
        is_terminal=is_terminal # New field to help frontend
    )

    # 2. HATEOAS Links Fix (ADDED DESCRIPTION HERE)
    links = {
        "self": {
            "href": f"/api/v1/users/{user.id}/status",
            "method": "GET",
            "description": "View overarching candidate status"
        }
    }

    if user.status == Status.IN_PROGRESS:
        links["next_action"] = {
            "href": "/api/v1/tasks/complete",
            "method": "PUT",
            "description": f"Submit payload for task: {user.current_task}"
        }

    return UserStatusResponse(
        user_id=user.id,
        email=user.email,
        status=user.status,
        current_step=user.current_step,
        current_task=user.current_task,
        custom_flow=user.custom_flow,
        progress=progress_info,
        _links=links # New HATEOAS object
    )
