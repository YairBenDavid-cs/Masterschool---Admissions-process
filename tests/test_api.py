import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repository.in_memory import InMemoryUserRepository
from app.repository.in_memory import get_repo 

client = TestClient(app)

# --- Test Environment Configuration ---

@pytest.fixture(autouse=True)
def fresh_repo():
    """
    Runs automatically before EVERY test. 
    Overrides the FastAPI dependency to inject a fresh, empty repository,
    ensuring complete data isolation (preventing test pollution).
    """
    clean_repo = InMemoryUserRepository()
    app.dependency_overrides[get_repo] = lambda: clean_repo
    
    yield # Test executes here
    
    app.dependency_overrides.clear()


# --- Helpers for Dynamic Discovery & Navigation ---

def get_flow_blueprint() -> dict:
    """Retrieves the full flow configuration from the API to avoid hardcoding names."""
    response = client.get("/api/v1/flow")
    assert response.status_code == 200, "Failed to fetch flow blueprint"
    return response.json()

def find_injection_task(blueprint: dict) -> tuple[str, str]:
    """Finds the first task and step that triggers a 'custom_flow' injection."""
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
    """Finds the first step in the configuration that contains more than one task."""
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
    Accepts an optional 'custom_payloads' dict to override standard passing payloads.
    """
    if custom_payloads is None:
        custom_payloads = {}
        
    user_data = current_user_data
    max_iterations = 20 # Circuit breaker to prevent infinite loops
    
    for _ in range(max_iterations):
        if user_data["current_step"] == target_step or user_data["status"] != "IN_PROGRESS":
            break
            
        current_task = user_data["current_task"]
        
        # Flex: Use custom payload if provided, otherwise fallback to generic passing values
        default_payload = {"score": 100, "decision": "passed_interview"}
        task_payload = custom_payloads.get(current_task, default_payload)

        payload = {
            "user_id": user_id,
            "step_name": user_data["current_step"],
            "task_name": current_task,
            "task_payload": task_payload
        }
        
        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Navigation failed at task '{current_task}'. Response: {res.text}"
        user_data = res.json()
        
    return user_data


# --- 1. User Management & HATEOAS Discovery ---

def test_create_user_and_discover_start():
    """
    POST /users - Validates that a new user is placed in the FIRST step 
    defined in the JSON, regardless of its name.
    """
    blueprint = get_flow_blueprint()
    expected_first_step = blueprint["steps"][0]["name"]
    expected_first_task = blueprint["steps"][0]["tasks"][0]

    response = client.post("/api/v1/users", json={"email": "dynamic.candidate@test.com"})
    assert response.status_code == 201
    data = response.json()
    
    assert "user_id" in data
    assert data["current_step"] == expected_first_step
    assert data["current_task"] == expected_first_task

def test_get_user_status_hateoas_progress():
    """
    GET /users/{id}/status - Validates that progress info (e.g., step index) 
    is calculated correctly based on the blueprint.
    """
    user_id = client.post("/api/v1/users", json={"email": "progress@test.com"}).json()["user_id"]
    
    response = client.get(f"/api/v1/users/{user_id}/status")
    assert response.status_code == 200
    data = response.json()
    
    assert "progress" in data
    assert data["progress"]["current_step_index"] == 1
    assert data["progress"]["total_steps"] == len(get_flow_blueprint()["steps"])


# --- 2. Dynamic Logic & Step Navigation ---

def test_multi_task_step_persistence():
    """
    PUT /tasks/complete - Verifies that a user remains on the same 'current_step' 
    if the step contains multiple tasks, until all tasks are completed.
    """
    blueprint = get_flow_blueprint()
    multi_task_step = get_multi_task_step(blueprint)
    
    if not multi_task_step:
        pytest.skip("No multi-task step found in current flow_config.json")
        
    target_step = multi_task_step["name"]
    first_task = multi_task_step["tasks"][0]
    second_task = multi_task_step["tasks"][1]

    initial_user = client.post("/api/v1/users", json={"email": "multitask@test.com"}).json()
    user_data = navigate_to_step(initial_user["user_id"], target_step, initial_user)
    
    assert user_data["current_step"] == target_step
    assert user_data["current_task"] == first_task
    
    # Submit ONLY the first task of this step
    res = client.put("/api/v1/tasks/complete", json={
        "user_id": user_data["user_id"],
        "step_name": target_step,
        "task_name": first_task,
        "task_payload": {"interview_date": "2026-05-01"} # Example generic payload
    })
    
    assert res.status_code == 200
    updated_data = res.json()
    
    # Assert the step did NOT change, but the task DID progress
    assert updated_data["current_step"] == target_step
    assert updated_data["current_task"] == second_task

def test_dynamic_task_injection_edge_case():
    """
    PUT /tasks/complete - Verifies that any task marked with 
    'inject_to_custom_flow' in the JSON correctly updates the user state.
    """
    blueprint = get_flow_blueprint()
    step_name, task_name = find_injection_task(blueprint)
    
    if not step_name:
        pytest.skip("No injection task found in current flow_config.json")

    initial_user = client.post("/api/v1/users", json={"email": "edge.case@test.com"}).json()
    user_data = navigate_to_step(initial_user["user_id"], step_name, initial_user)
    
    # Submit the specific payload known to trigger the injection condition
    payload = {
        "user_id": user_data["user_id"],
        "step_name": step_name,
        "task_name": task_name,
        "task_payload": {"score": 65} # The defining threshold for 'Second Chance'
    }
    
    response = client.put("/api/v1/tasks/complete", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    # Verify injection occurred successfully
    assert len(data["custom_flow"]) > 0
    assert data["current_task"] in data["custom_flow"]


# --- 3. Terminal States & Security Guards ---

def test_terminal_state_lock():
    """
    PUT /tasks/complete - Validates that once a user reaches a terminal state 
    (ACCEPTED/REJECTED), they are locked and cannot process further tasks.
    """
    initial_user = client.post("/api/v1/users", json={"email": "terminal@test.com"}).json()
    user_id = initial_user["user_id"]
    
    # Navigate to a non-existent step to force reaching the end of the flow
    user_data = navigate_to_step(user_id, "NON_EXISTENT_STEP_TO_FORCE_COMPLETION", initial_user)
        
    assert user_data["status"] in ["ACCEPTED", "REJECTED"], "User did not reach terminal state"
    
    # Attempt to perform an action after reaching terminal state
    payload = {
        "user_id": user_id,
        "step_name": user_data["current_step"], 
        "task_name": user_data["current_task"],
        "task_payload": {}
    }
    response = client.put("/api/v1/tasks/complete", json=payload)
    
    # Verify the system locks them out with a 400 Bad Request
    assert response.status_code == 400
    assert "terminal state" in response.json()["detail"].lower()

def test_error_task_mismatch():
    """PUT /tasks/complete - Should return 400 if user tries to submit the wrong step/task."""
    user_id = client.post("/api/v1/users", json={"email": "mismatch@test.com"}).json()["user_id"]
    
    payload = {
        "user_id": user_id,
        "step_name": "hacked_step",
        "task_name": "hacked_task",
        "task_payload": {}
    }
    response = client.put("/api/v1/tasks/complete", json=payload)
    assert response.status_code == 400
    assert "mismatch" in response.json()["detail"].lower()

def test_error_user_not_found():
    """GET /users/{id}/status - Should return 404 for invalid IDs."""
    response = client.get("/api/v1/users/non-existent-uuid/status")
    assert response.status_code == 404


# --- 4. The Full Journey (HATEOAS Compliance) ---

def test_complete_flow_following_api_instructions():
    """
    End-to-End: This test simply 'follows' the current_task and current_step 
    provided by the API until it reaches a terminal state, proving complete decoupling.
    """
    response = client.post("/api/v1/users", json={"email": "full.journey@test.com"})
    assert response.status_code == 201
    user_data = response.json()
    user_id = user_data["user_id"]

    max_iterations = 20 
    for _ in range(max_iterations):
        if user_data["status"] in ["ACCEPTED", "REJECTED"]:
            break
            
        payload = {
            "user_id": user_id,
            "step_name": user_data["current_step"],
            "task_name": user_data["current_task"],
            "task_payload": {"score": 100, "decision": "passed_interview"} 
        }
        res = client.put("/api/v1/tasks/complete", json=payload)
        assert res.status_code == 200, f"Failed at step: {user_data['current_step']}"
        user_data = res.json()

    assert user_data["status"] in ["ACCEPTED", "REJECTED"]