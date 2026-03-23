from enum import Enum
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

class PassConditionType(str, Enum):
    """
    Defines how a task is evaluated for completion.
    """
    AUTO_PASS = "AUTO_PASS"
    EVALUATE_PAYLOAD = "EVALUATE_PAYLOAD"

class Status(str, Enum):
    """
    Represents the overall admission status of the user.
    """
    IN_PROGRESS = "IN_PROGRESS"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"

class TransitionRule(BaseModel):
    """
    Represents a single edge in the FSM directed graph.
    
    Attributes:
        condition (str): A python-evaluable string condition (e.g., "payload.get('score', 0) > 75") or 'DEFAULT'.
        next_step (str): The ID of the next step. Can be a terminal state like 'TERMINAL_REJECTED'.
        next_task (str): The ID of the next task, or 'NONE' if terminating.
        mark_status (Optional[Status]): If reached, updates the user's overall status (e.g., ACCEPTED/REJECTED).
        inject_to_custom_flow (bool): Whether to inject the next_task into the user's custom flow list.
    """
    condition: str = Field(..., description="The python-evaluable condition, or 'DEFAULT'")
    next_step: str = Field(..., description="The ID of the next step (or terminal state)")
    next_task: str = Field(..., description="The ID of the next task (or 'NONE')")
    mark_status: Optional[Status] = Field(default=None, description="Updates overall status if reached")
    
    inject_to_custom_flow: bool = Field(
        default=False, 
        description="Whether to inject the next_task into the user's custom flow list"
    )

class TaskBlueprint(BaseModel):
    """
    The blueprint for a specific task within the flow.
    
    Attributes:
        name (str): The unique identifier of the task.
        pass_condition_type (PassConditionType): How the engine should evaluate this task.
        transitions (List[TransitionRule]): An ordered list of rules to evaluate next steps.
    """
    name: str = Field(..., description="Task unique identifier")
    pass_condition_type: PassConditionType = Field(..., description="Evaluation strategy for the task")
    transitions: List[TransitionRule] = Field(..., description="Possible transitions from this task")

class StepBlueprint(BaseModel):
    """
    The blueprint for a high-level step, primarily used for UI progress representation.
    
    Attributes:
        name (str): The unique identifier of the step.
        display_name (str): Human-readable name for the frontend.
        tasks (List[str]): List of task IDs belonging to this step.
    """
    name: str = Field(..., description="Step unique identifier")
    display_name: str = Field(..., description="Human-readable step name")
    tasks: List[str] = Field(..., description="List of task IDs in this step")

class FlowConfig(BaseModel):
    """
    The root configuration object representing the entire admissions flow.
    
    Attributes:
        default_steps (List[StepBlueprint]): The sequential steps shown to standard users.
        tasks_map (Dict[str, TaskBlueprint]): A fast-lookup dictionary for task evaluation.
    """
    default_steps: List[StepBlueprint] = Field(..., description="Ordered list of standard steps")
    tasks_map: Dict[str, TaskBlueprint] = Field(..., description="Mapping of task IDs to their blueprints")