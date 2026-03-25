"""
FastAPI route definitions for the Admissions Engine REST API.
"""

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict
from uuid import UUID

# Local Application — Domain & Config
from app.models.domain import User
from app.core.config_models import FlowConfig, Status

# Local Application — Schemas for request validation and response modeling
from app.models.schemas import (
    UserCreateRequest,
    UserStatusResponse,
    TaskCompleteRequest,
    FlowDefinitionResponse,
    ProgressInfo,
    UserFlowResponse,
)

# Local Application — Services & Exceptions
from app.services.admissions import (
    create_new_user,
    get_user_record,
    process_task_completion,
    get_user_flow,
    build_personalized_task_sequence,
    build_user_flow_data,
    UserNotFoundError,
    EmailAlreadyExistsError,
    WorkflowStateError,
    TaskMismatchError,
    ConfigurationError,
    PayloadValidationError,
)

# Local Application — Dependencies
from app.core.config import get_flow_config
from app.repository.in_memory import get_repo, UserRepository

# Local Application — OpenAPI error response documentation
from app.api.docs_responses import (
    POST_USERS_400,
    POST_USERS_422,
    PUT_TASKS_COMPLETE_400,
    PUT_TASKS_COMPLETE_404,
    PUT_TASKS_COMPLETE_422,
    PUT_TASKS_COMPLETE_500,
    USER_LOOKUP_404,
    DEFAULT_VALIDATION_422,
)

router = APIRouter(prefix="/api/v1", tags=["Admissions Flow"])


# =============================================================================
# 1. POST - Create a user in the system
# =============================================================================

@router.post(
    "/users",
    summary="Register a New Candidate",
    response_model=UserStatusResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: POST_USERS_400, 422: POST_USERS_422}
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
# 2A. GET - Retrieve the entire flow
# =============================================================================

@router.get(
    "/flow",
    summary="Retrieve the Full FSM Flow Blueprint",
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
# 2B. GET - Retrieve the personalized flow for a specific user
# =============================================================================

@router.get(
    "/users/{user_id}/flow",
    summary="Get Candidate's Personalized Flow",
    response_model=UserFlowResponse,
    status_code=status.HTTP_200_OK,
    responses={404: USER_LOOKUP_404, 422: DEFAULT_VALIDATION_422}
)
def get_user_personalized_flow(
    user_id: UUID,
    repo: UserRepository = Depends(get_repo),
    flow: FlowConfig = Depends(get_flow_config)
) -> UserFlowResponse:
    """
    Returns the user's personalized ordered task sequence with per-task state annotations.

    Merges the global default steps with any dynamically injected tasks (e.g., second_chance_iq),
    inserting custom tasks at the correct logical position. Each task is annotated as
    COMPLETED, CURRENT, or PENDING based on the user's current FSM position.

    Args:
        user_id (UUID): The unique identifier of the user (path parameter, validated as UUID v4).
        repo (UserRepository): The injected persistence layer dependency.
        flow (FlowConfig): The injected FSM configuration dependency.

    Returns:
        UserFlowResponse: The personalized task list with states and total task count.

    Raises:
        HTTPException: 404 Not Found if the user ID does not exist.
    """
    try:
        user, task_sequence = get_user_flow(str(user_id), repo, flow)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    tasks, current_task_number, outcome = build_user_flow_data(user, task_sequence, flow)

    return UserFlowResponse(
        user_id=user.id,
        status=user.status,
        total_tasks=len(task_sequence),
        current_task_number=current_task_number,
        tasks=tasks,
        outcome=outcome,
    )


# =============================================================================
# 3. GET - Fetch the current step and task for a specific user
# =============================================================================

@router.get(
    "/users/{user_id}/current",
    summary="Get Candidate's Current Step & Task",
    response_model=Dict[str, str],
    status_code=status.HTTP_200_OK,
    responses={404: USER_LOOKUP_404, 422: DEFAULT_VALIDATION_422}
)
def get_user_current_step_and_task(
    user_id: UUID,
    repo: UserRepository = Depends(get_repo)
) -> Dict[str, str]:
    """
    Returns only the current step and task for a specific user.

    A lightweight endpoint optimized for polling scenarios where the
    client only needs to know the user's position in the workflow,
    without the full enriched response payload.

    Args:
        user_id (UUID): The unique identifier of the user (path parameter, validated as UUID v4).
        repo (UserRepository): The injected persistence layer dependency.

    Returns:
        Dict[str, str]: A dictionary containing 'current_step' and
            'current_task' keys.

    Raises:
        HTTPException: 404 Not Found if the user ID does not exist.
    """
    try:
        user = get_user_record(user_id=str(user_id), repo=repo)
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
    summary="Complete a Task & Advance the FSM",
    response_model=UserStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={400: PUT_TASKS_COMPLETE_400, 404: PUT_TASKS_COMPLETE_404, 422: PUT_TASKS_COMPLETE_422, 500: PUT_TASKS_COMPLETE_500}
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
            user_id, current_step, current_task, and task_payload.
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
            user_id=str(request.user_id),
            current_step=request.step_name,
            current_task=request.task_name,
            payload=request.task_payload,
            repo=repo,
            flow=flow
        )
        return _build_user_response(user, flow)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PayloadValidationError as exc:
        # Contract violation (422) - payload doesn't match the task's declared schema
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
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
    summary="Get Candidate's Admission Status",
    response_model=Dict[str, str],
    status_code=status.HTTP_200_OK,
    responses={404: USER_LOOKUP_404, 422: DEFAULT_VALIDATION_422}
)
def get_user_status(
    user_id: UUID,
    repo: UserRepository = Depends(get_repo)
) -> Dict[str, str]:
    """
    Returns only the overarching admission status for a specific user.

    A lightweight endpoint that returns the user's high-level status
    (IN_PROGRESS, ACCEPTED, or REJECTED) without step or task details,
    optimized for dashboard polling and status badge rendering.

    Args:
        user_id (UUID): The unique identifier of the user (path parameter, validated as UUID v4).
        repo (UserRepository): The injected persistence layer dependency.

    Returns:
        Dict[str, str]: A dictionary containing a single 'status' key.

    Raises:
        HTTPException: 404 Not Found if the user ID does not exist.
    """
    try:
        user = get_user_record(user_id=str(user_id), repo=repo)
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
    ratio, and constructs navigational HATEOAS links that guide the
    client on what actions are available next.

    Args:
        user (User): The domain user entity containing current workflow state.
        flow (FlowConfig): The FSM configuration used to derive step ordering
            and total step count for progress calculations.

    Returns:
        UserStatusResponse: A fully enriched response DTO containing user
            state, progress info, and HATEOAS navigation links.
    """
    # Build personalized task sequence for dynamic, per-user progress
    task_sequence = build_personalized_task_sequence(user, flow)
    total_tasks = len(task_sequence)
    is_terminal = user.status in [Status.ACCEPTED, Status.REJECTED]

    if not is_terminal and user.current_task and user.current_task in task_sequence:
        current_idx = task_sequence.index(user.current_task)
        completion_ratio = f"{current_idx}/{total_tasks}"
    elif user.status == Status.ACCEPTED:
        current_idx = total_tasks
        completion_ratio = f"{total_tasks}/{total_tasks}"
    else:
        # REJECTED: use last_completed_task position if available for accurate display
        if user.last_completed_task and user.last_completed_task in task_sequence:
            current_idx = task_sequence.index(user.last_completed_task) + 1
        else:
            current_idx = 0
        completion_ratio = f"{current_idx}/{total_tasks}"

    progress_info = ProgressInfo(
        current_step_index=current_idx,
        total_steps=total_tasks,
        completion_ratio=completion_ratio,
        is_terminal=is_terminal,
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

    # 3. JIT Schema Discovery: include the current task's payload contract
    current_task_schema = []
    if user.status == Status.IN_PROGRESS and user.current_task:
        task_bp = flow.tasks_map.get(user.current_task)
        if task_bp:
            current_task_schema = task_bp.payload_schema

    return UserStatusResponse(
        user_id=user.id,
        email=user.email,
        status=user.status,
        current_step=user.current_step,
        current_task=user.current_task,
        custom_flow=user.custom_flow,
        progress=progress_info,
        _links=links,
        current_task_schema=current_task_schema,
    )
