"""
Request and response DTOs (Data Transfer Objects) for the Admissions Engine API.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, EmailStr, ConfigDict

# Importing Enums and Blueprints for strict typing and Swagger documentation
from app.core.config_models import Status, StepBlueprint, TaskBlueprint

# =============================================================================
# REQUEST DTOs (Data Transfer Objects)
# =============================================================================

class UserCreateRequest(BaseModel):
    """
    Payload required to create a new user and initiate their admissions flow.
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "candidate@masterschool.com"
            }
        }
    )

    email: EmailStr = Field(
        ...,
        description="Valid email address of the applicant. Strongly validated to prevent garbage data."
    )


class TaskCompleteRequest(BaseModel):
    """
    The incoming webhook/API payload to mark a specific task as completed.

    The `task_payload` is a generic dictionary, allowing extreme flexibility
    for the Product Managers to send any dynamic data structure
    (e.g., {"score": 75} or {"decision": "passed_interview"}).
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "paste-your-user-id-from-step-1-here",
                "current_step": "personal_details",
                "current_task": "submit_personal_details",
                "task_payload": {}
            }
        }
    )

    user_id: str = Field(..., description="The unique identifier of the user.")
    current_step: str = Field(..., description="The step the task belongs to — must match the user's current step.")
    current_task: str = Field(..., description="The specific task being completed — must match the user's current task.")
    task_payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dynamic FSM evaluation data. Leave empty `{}` for AUTO_PASS tasks (e.g., Step 1: Personal Details). "
            "For evaluated tasks, send the relevant result — e.g., `{\"score\": 82}` for the IQ Test "
            "or `{\"decision\": \"passed_interview\"}` for the Interview."
        )
    )


# =============================================================================
# PRESENTATION & METADATA MODELS (Enrichments)
# =============================================================================

class ProgressInfo(BaseModel):
    """
    Encapsulates the user's progress statistics.
    Allows the frontend to render progress bars blindly, without knowing 
    the underlying FSM logic or the number of steps.
    """
    current_step_index: int = Field(
        ..., 
        description="The 1-based index of the user's current standard step."
    )
    total_steps: int = Field(
        ..., 
        description="The total number of standard steps in the flow definition."
    )
    completion_ratio: str = Field(
        ...,
        description=(
            "Step completion ratio as a human-readable fraction (e.g., '1/6'). "
            "Suitable for direct display in UI labels."
        ),
        examples=["1/6", "3/6", "6/6"],
    )
    is_terminal: bool = Field(
        ...,
        description="True if the user has reached ACCEPTED or REJECTED. Overrides completion_ratio visuals."
    )


class HateoasLink(BaseModel):
    """
    Represents a RESTful HATEOAS action link.
    Instructs the frontend on exactly what endpoints it can call next.
    """
    href: str = Field(..., description="The API URL to call.")
    method: str = Field(..., description="The HTTP method to use (e.g., PUT, GET).")
    description: str = Field(..., description="Human-readable description of what this action does.")


# =============================================================================
# RESPONSE DTOs
# =============================================================================

class UserStatusResponse(BaseModel):
    """
    A highly enriched presentation model detailing the user's current state.
    This separates the API response from the raw Database Domain model.
    """
    model_config = ConfigDict(populate_by_name=True) # Allows using _links in Python kwargs

    user_id: str = Field(..., description="The unique User ID.")
    email: EmailStr = Field(..., description="The user's registered email.")
    status: Status = Field(..., description="The overarching status (IN_PROGRESS, ACCEPTED, REJECTED).")
    
    current_step: Optional[str] = Field(None, description="The programmatic name of the current step.")
    current_task: Optional[str] = Field(None, description="The programmatic name of the pending task.")
    
    custom_flow: List[str] = Field(
        default_factory=list, 
        description="A list of dynamically injected tasks specifically for this user (e.g., Second Chance tests)."
    )
    
    progress: ProgressInfo = Field(
        ..., 
        description="Dynamic progress calculations for UI rendering."
    )
    
    links: Dict[str, HateoasLink] = Field(
        default_factory=dict, 
        alias="_links", # Adheres to HAL/HATEOAS JSON standards by prefixing with underscore
        description="HATEOAS links detailing the next permitted actions for this user."
    )


class FlowDefinitionResponse(BaseModel):
    """
    Response model for exposing the global FSM blueprint to the frontend.
    Enables dynamic rendering of the step map.
    """
    steps: List[StepBlueprint] = Field(
        ..., 
        description="The ordered sequence of standard steps in the flow."
    )
    tasks_map: Dict[str, TaskBlueprint] = Field(
        ..., 
        description="A dictionary detailing the validation and transition rules for every task."
    )