"""Shared TestClient instance and navigation helper functions for API-level tests."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Full spec-compliant default passing payloads for every task.
# Used by navigation helpers so tests don't need to provide complete payloads manually.
DEFAULT_TASK_PAYLOADS: dict[str, dict] = {
    "submit_personal_details": {
        "first_name": "Test", "last_name": "User",
        "email": "test@example.com", "timestamp": 1700000000,
    },
    "perform_iq_test": {"score": 100, "test_id": "test-001", "timestamp": 1700000000},
    "second_chance_iq": {"score": 100},
    "schedule_interview": {"interview_date": "2025-01-01"},
    "perform_interview": {
        "decision": "passed_interview",
        "interview_date": "2025-01-01",
        "interviewer_id": "int-001",
    },
    "upload_identification_document": {"passport_number": "AB123456", "timestamp": 1700000000},
    "sign_contract_task": {"timestamp": 1700000000},
    "process_payment": {"payment_id": "pay-001", "timestamp": 1700000000},
    "join_slack_task": {"email": "test@example.com", "timestamp": 1700000000},
}


def get_flow_blueprint() -> dict:
    """
    Retrieves the full flow configuration from the API to avoid hardcoding names.

    Returns:
        dict: The parsed JSON response containing 'steps' and 'tasks_map'.
    """
    response = client.get("/api/v1/flow")
    assert response.status_code == 200, "Failed to fetch flow blueprint"
    return response.json()

def find_injection_task(blueprint: dict) -> tuple[str, str]:
    """
    Finds the first task and step that triggers a 'custom_flow' injection.

    Args:
        blueprint (dict): The full flow configuration as returned by the
            GET /flow endpoint.

    Returns:
        tuple[str, str]: A (step_name, task_id) pair for the first task
            with an inject_to_custom_flow transition, or (None, None)
            if no such task exists.
    """
    for step in blueprint["steps"]:
        for task_id in step["tasks"]:
            task_bp = blueprint.get("tasks_map", {}).get(task_id)
            if not task_bp:
                continue
            for transition in task_bp.get("transitions", []):
                if transition.get("inject_to_custom_flow"):
                    return step["name"], task_id
    return None, None

def get_multi_task_step(blueprint: dict) -> dict:
    """
    Finds the first step in the configuration that contains more than one task.

    Args:
        blueprint (dict): The full flow configuration as returned by the
            GET /flow endpoint.

    Returns:
        dict: The step dictionary containing 'name' and 'tasks', or None
            if no multi-task step exists.
    """
    for step in blueprint["steps"]:
        if len(step["tasks"]) > 1:
            return step
    return None

def navigate_to_step(
    user_id: str,
    target_step: str,
    current_user_data: dict,
    custom_payloads: dict = None
) -> dict:
    """
    Helper to dynamically advance a user to a specific step.

    Repeatedly submits task completions using the API-provided step_name
    and task_name until the user reaches the target step or a terminal
    state. Accepts an optional custom_payloads dict to override standard
    passing payloads for specific tasks.

    Args:
        user_id (str): The unique identifier of the user to advance.
        target_step (str): The name of the step to navigate toward.
        current_user_data (dict): The current API response containing
            the user's state (step_name, task_name, status).
        custom_payloads (dict): Optional mapping of task_name to payload
            dict, used to override the default passing payload for
            specific tasks.

    Returns:
        dict: The final API response after navigation completes, containing
            the user's updated state.
    """
    if custom_payloads is None:
        custom_payloads = {}

    user_data = current_user_data
    max_iterations = 20  # Circuit breaker to prevent infinite loops

    for _ in range(max_iterations):
        if user_data["step_name"] == target_step or user_data["status"] != "IN_PROGRESS":
            break

        task_name = user_data["task_name"]

        # Use custom payload if provided, otherwise fall back to spec-compliant defaults
        task_payload = custom_payloads.get(task_name, DEFAULT_TASK_PAYLOADS.get(task_name, {}))

        payload = {
            "user_id": user_id,
            "step_name": user_data["step_name"],
            "task_name": task_name,
            "task_payload": task_payload
        }

        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Navigation failed at task '{task_name}'. Response: {res.text}"
        user_data = res.json()

    return user_data

def navigate_to_task(
    user_id: str,
    target_task: str,
    current_user_data: dict,
    custom_payloads: dict = None
) -> dict:
    """
    Advances a user through the flow until they reach a specific task name.

    Similar to navigate_to_step but stops at task granularity, allowing
    tests to target specific tasks within multi-task steps.

    Args:
        user_id (str): The unique identifier of the user to advance.
        target_task (str): The name of the task to navigate toward.
        current_user_data (dict): The current API response containing
            the user's state (step_name, task_name, status).
        custom_payloads (dict): Optional mapping of task_name to payload
            dict, used to override the default passing payload for
            specific tasks.

    Returns:
        dict: The final API response after navigation completes, containing
            the user's updated state.
    """
    if custom_payloads is None:
        custom_payloads = {}

    user_data = current_user_data
    max_iterations = 20  # Circuit breaker to prevent infinite loops

    for _ in range(max_iterations):
        if user_data["task_name"] == target_task or user_data["status"] != "IN_PROGRESS":
            break

        task_name = user_data["task_name"]

        # Use custom payload if provided, otherwise fall back to spec-compliant defaults
        task_payload = custom_payloads.get(task_name, DEFAULT_TASK_PAYLOADS.get(task_name, {}))

        payload = {
            "user_id": user_id,
            "step_name": user_data["step_name"],
            "task_name": task_name,
            "task_payload": task_payload
        }

        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Navigation failed at task '{task_name}'. Response: {res.text}"
        user_data = res.json()

    return user_data
