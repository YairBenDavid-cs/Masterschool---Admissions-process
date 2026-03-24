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
    user_id: str = Field(..., description="The unique identifier of the user.")
    step_name: str = Field(..., description="The step the task belongs to (for validation).")
    task_name: str = Field(..., description="The specific task being completed.")
    task_payload: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Dynamic data containing the test results or form inputs to be evaluated by the FSM."
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
    percentage: float = Field(
        ..., 
        description="Calculated progress percentage (e.g., 50.0). Safe for UI width binding."
    )
    is_terminal: bool = Field(
        ..., 
        description="True if the user has reached ACCEPTED or REJECTED. Overrides percentage visuals."
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