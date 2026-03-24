"""
Domain model representing the applicant entity within the admissions FSM.
"""

# Standard Library
from datetime import datetime, timezone
from typing import List, Optional

# Third-Party
from pydantic import BaseModel, Field

# Local Application
from app.core.config_models import Status


# =============================================================================
# DOMAIN MODEL
# =============================================================================

class User(BaseModel):
    """
    Represents an applicant/user in the admissions state machine.

    This model holds the current state of the user. It tracks where they are
    in the flow and maintains a record of any dynamically added tasks
    (like a second-chance IQ test) specifically tailored to them.

    Attributes:
        id (str): The unique identifier for the user.
        email (str): The user's email address.
        status (Status): The overall status of their application (IN_PROGRESS, ACCEPTED, REJECTED).
        current_step (Optional[str]): The ID of the step the user is currently facing.
        current_task (Optional[str]): The ID of the task the user needs to complete next.
        custom_flow (List[str]): A list of dynamic task IDs appended only for this user.
    """
    id: str = Field(..., description="Unique identifier for the user")
    email: str = Field(..., description="User's email address")
    status: Status = Field(default=Status.IN_PROGRESS, description="Overall admission status")

    # Fields provided during the 'Personal Details' step
    first_name: Optional[str] = Field(None, description="Applicant's first name")
    last_name: Optional[str] = Field(None, description="Applicant's last name")

    # Audit trail
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc),description="Timestamp of registration")

    # State tracking
    current_step: Optional[str] = Field(default=None, description="Current step ID")
    current_task: Optional[str] = Field(default=None, description="Current task ID")

    # The dynamic flows
    custom_flow: List[str] = Field(
        default_factory=list,
        description="Dynamically added tasks specific to this user (e.g., second_chance_iq)"
    )

    # Terminal state tracking
    last_completed_task: Optional[str] = Field(
        default=None,
        description="The last task completed before transitioning to terminal or current state."
    )

    def is_terminated(self) -> bool:
        """
        Checks if the user's workflow has reached a terminal state.

        Returns:
            bool: True if ACCEPTED or REJECTED, False if IN_PROGRESS.
        """
        return self.status in [Status.ACCEPTED, Status.REJECTED]
