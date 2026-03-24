from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

# Domain & Config
from app.models.domain import User
from app.core.config_models import FlowConfig, Status

# Schemas (Ensure these exist in your app/models/schemas.py)
from app.models.schemas import (
    UserCreateRequest, 
    UserStatusResponse, 
    TaskCompleteRequest, 
    FlowDefinitionResponse, 
    ProgressInfo
)

# Services & Exceptions
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

# Dependencies 
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

    # 2. HATEOAS Links Fix
    links = {
        "self": {"href": f"/api/v1/users/{user.id}/status", "method": "GET"}
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