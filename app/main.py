import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

# Router import
from app.api.routes import router as api_router

# Configuration and Core imports
from app.core.config import load_flow_config, get_flow_config, Settings
from app.core.config_models import PassConditionType
from app.core.engine import EngineEvaluationError

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# LIFECYCLE EVENTS (Replaces @app.on_event)
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Executes on application startup and shutdown.
    
    Validates that the immutable FSM flow configuration can be loaded successfully.
    Adheres to the "Fail-Fast" principle: if the configuration is missing or 
    corrupted, the application refuses to start.
    """
    logger.info("Starting up Masterschool Admissions Engine...")
    try:
        settings = Settings()
        # Attempt to load and parse the flow_config.json via Pydantic
        load_flow_config(settings=settings)
        logger.info("Successfully loaded and validated the FSM flow configuration.")
    except Exception as exc:
        logger.critical(f"FATAL: Failed to load FSM configuration on startup: {exc}")
        # Stop the server from starting if the core brain is broken
        raise RuntimeError("Application cannot start without a valid flow configuration.") from exc
        
    yield  # The FastAPI application runs here
    
    # Teardown/Shutdown logic would go here if needed (e.g., closing DB connections)
    logger.info("Shutting down Admissions Engine...")


# =============================================================================
# FASTAPI APPLICATION INSTANCE
# =============================================================================
app = FastAPI(
    title="Masterschool Admissions Engine",
    description="""
<div align="center">

# 🎓 Masterschool Admissions Engine

**A production-grade, Metadata-Driven Finite State Machine API**
Built on a 100% domain-agnostic engine — all flow logic lives in `flow_config.json`.
No code changes needed when a PM updates the funnel. Full **HATEOAS** compliance built-in.

</div>

---

## ⚡ Quick Start — Run a Full Flow in 3 Steps

> All examples are pre-filled. Just copy your `user_id` between steps.

### Step 1 · Register a Candidate 🆕
**`POST /api/v1/users`** → click **Try it out** → **Execute**
The email is pre-filled. Copy the `user_id` from the response.

### Step 2 · Advance Through the Flow 🔄
**`PUT /api/v1/tasks/complete`** → paste your `user_id` → **Execute**
Each response returns the **next** `current_step` and `current_task` via `_links`.
Repeat until `status` is `ACCEPTED` or `REJECTED`.

### Step 3 · Check the Final Decision ✅
**`GET /api/v1/users/{user_id}/status`** → paste your `user_id`
Returns the candidate's current status and progress at any point in the flow.

---

## 🗺️ Admissions Funnel

| # | Step | Task | Type |
|---|------|------|------|
| 1 | Personal Details | `submit_personal_details` | Auto-pass |
| 2 | IQ Test | `perform_iq_test` | Evaluated payload |
| ↳ | *(if score < 70)* | `second_chance_iq` | Injected · Evaluated payload |
| 3 | Interview | `schedule_interview` | Auto-pass |
| 4 | Interview | `perform_interview` | Evaluated payload |
| 5 | Sign Contract | `upload_identification_document` | Auto-pass |
| 6 | Sign Contract | `sign_contract_task` | Auto-pass |
| 7 | Payment | `process_payment` | Auto-pass |
| 8 | Join Slack | `join_slack_task` | Auto-pass → **ACCEPTED** |

---

<details>
<summary>🛠️ Copy-Paste Payload Cheat Sheet</summary>

### 1 · `submit_personal_details` — Personal Details *(Auto-pass)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "personal_details",
  "current_task": "submit_personal_details",
  "task_payload": {}
}
```

---

### 2 · `perform_iq_test` — IQ Test *(Evaluated)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "iq_test",
  "current_task": "perform_iq_test",
  "task_payload": {
    "score": 85
  }
}
```
> 💡 Score **≥ 70** to pass. Use `40` to trigger the second-chance path.

---

### 3 · `second_chance_iq` — Second-Chance IQ *(Injected · Evaluated)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "iq_test",
  "current_task": "second_chance_iq",
  "task_payload": {
    "score": 80
  }
}
```
> 💡 Only appears if `perform_iq_test` score was below threshold. Same scoring rules apply.

---

### 4 · `schedule_interview` — Schedule Interview *(Auto-pass)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "interview",
  "current_task": "schedule_interview",
  "task_payload": {}
}
```

---

### 5 · `perform_interview` — Interview Decision *(Evaluated)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "interview",
  "current_task": "perform_interview",
  "task_payload": {
    "decision": "pass"
  }
}
```
> 💡 Allowed values: `"pass"` · `"fail"`

---

### 6 · `upload_identification_document` — Upload ID *(Auto-pass)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "sign_contract",
  "current_task": "upload_identification_document",
  "task_payload": {}
}
```

---

### 7 · `sign_contract_task` — Sign Contract *(Auto-pass)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "sign_contract",
  "current_task": "sign_contract_task",
  "task_payload": {}
}
```

---

### 8 · `process_payment` — Payment *(Auto-pass)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "payment",
  "current_task": "process_payment",
  "task_payload": {}
}
```

---

### 9 · `join_slack_task` — Join Slack *(Auto-pass → ACCEPTED)*
```json
{
  "user_id": "<your-user-id>",
  "current_step": "join_slack",
  "current_task": "join_slack_task",
  "task_payload": {}
}
```

</details>
""",
    version="1.0.0",
    docs_url="/docs",   # Swagger UI
    redoc_url="/redoc", # ReDoc UI
    lifespan=lifespan   # Attaching the new lifespan context manager
)

# Mount the API routes defined in app/api/routes.py
app.include_router(api_router)


# =============================================================================
# GLOBAL EXCEPTION HANDLERS
# =============================================================================
@app.exception_handler(EngineEvaluationError)
async def engine_evaluation_error_handler(request: Request, exc: EngineEvaluationError) -> JSONResponse:
    """
    Globally catches EngineEvaluationError (e.g., when eval() fails due to 
    corrupted Python syntax inside the JSON config).
    
    Returns a safe 500 Internal Server Error, masking the raw internal Python 
    exceptions from the end-user for security reasons.
    """
    logger.error(f"CRITICAL: Engine evaluation failed during request {request.url.path} | Error: {exc}")
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error during rule evaluation. Please contact system administrator."
        }
    )


# =============================================================================
# HEALTH PROBES
# =============================================================================
@app.get("/health", summary="API Health Check", tags=["System"])
def health_check() -> dict[str, str]:
    """
    Liveness probe endpoint.
    Used by container orchestration tools (like Docker Compose or Kubernetes) 
    to verify the application process is running and responsive.
    
    Returns:
        dict: A simple health status indicator.
    """
    return {"status": "healthy"}


# =============================================================================
# DYNAMIC OPENAPI / SWAGGER OVERRIDE
# =============================================================================

def _patch_path_example(paths: dict, path: str, method: str, example: dict) -> None:
    """Injects a 200 response body example directly at the path operation level.

    Used for endpoints that return Dict[str, str] — these have no named schema in
    components/schemas, so the example must be written to the paths object instead.
    """
    target = (
        paths
        .get(path, {})
        .get(method, {})
        .get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json")
    )
    if target is not None:
        target["example"] = example


def _build_dynamic_openapi() -> dict:
    """
    Generates the OpenAPI schema with examples derived from flow_config.json.

    Cached after first generation via app.openapi_schema — regenerated on
    next server restart when the config changes. Zero Python changes needed
    when a PM updates example values in flow_config.json.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    flow = get_flow_config()

    # Find the first EVALUATE_PAYLOAD task that has at least one example defined
    example_task = next(
        (bp for bp in flow.tasks_map.values()
         if bp.pass_condition_type == PassConditionType.EVALUATE_PAYLOAD
         and bp.payload_schema
         and any(f.example is not None for f in bp.payload_schema)),
        None
    )

    if example_task:
        payload_example = {
            f.key_name: f.example
            for f in example_task.payload_schema
            if f.example is not None
        }
        task_step_name = next(
            (step.name for step in flow.default_steps if example_task.name in step.tasks),
            example_task.name
        )

        schemas = schema.get("components", {}).get("schemas", {})

        if "TaskCompleteRequest" in schemas and payload_example:
            schemas["TaskCompleteRequest"]["example"] = {
                "user_id": "<paste-user-id-from-POST-/users>",
                "current_step": task_step_name,
                "current_task": example_task.name,
                "task_payload": payload_example
            }

        if "UserStatusResponse" in schemas:
            schema_example_fields = [
                {
                    "key_name": f.key_name,
                    "value_type": f.value_type,
                    "required": f.required,
                    "description": f.description,
                    "example": f.example,
                }
                for f in example_task.payload_schema
            ]
            schemas["UserStatusResponse"]["example"] = {
                "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "email": "candidate@masterschool.com",
                "status": "IN_PROGRESS",
                "current_step": task_step_name,
                "current_task": example_task.name,
                "custom_flow": [],
                "progress": {
                    "current_step_index": 1,
                    "total_steps": 8,
                    "completion_ratio": "1/8",
                    "is_terminal": False
                },
                "_links": {
                    "self": {
                        "href": "/api/v1/users/a1b2c3d4-.../status",
                        "method": "GET",
                        "description": "View overarching candidate status"
                    },
                    "next_action": {
                        "href": "/api/v1/tasks/complete",
                        "method": "PUT",
                        "description": f"Submit payload for task: {example_task.name}"
                    }
                },
                "current_task_schema": schema_example_fields
            }

        # --- FlowDefinitionResponse: built from live config (first 3 tasks for brevity) ---
        if "FlowDefinitionResponse" in schemas:
            example_steps = [
                {"name": step.name, "display_name": step.display_name, "tasks": step.tasks}
                for step in flow.default_steps
            ]
            example_tasks_map = {
                task_id: {
                    "name": bp.name,
                    "pass_condition_type": bp.pass_condition_type.value,
                    "payload_schema": [
                        {
                            "key_name": f.key_name,
                            "value_type": f.value_type,
                            "required": f.required,
                            "description": f.description,
                            "example": f.example,
                        }
                        for f in bp.payload_schema
                    ],
                    "transitions": [
                        {"condition": t.condition, "next_step": t.next_step, "next_task": t.next_task}
                        for t in bp.transitions[:1]
                    ],
                }
                for task_id, bp in list(flow.tasks_map.items())[:3]
            }
            schemas["FlowDefinitionResponse"]["example"] = {
                "steps": example_steps,
                "tasks_map": example_tasks_map,
            }

        # --- UserFlowResponse: realistic rejection snapshot ---
        if "UserFlowResponse" in schemas:
            default_tasks = [task for step in flow.default_steps for task in step.tasks]
            task_to_step = {
                task_id: step.name
                for step in flow.default_steps
                for task_id in step.tasks
            }
            states = ["COMPLETED", "COMPLETED", "FAILED", "PENDING", "PENDING"]
            flow_tasks_example = [
                {
                    "task_id": task_id,
                    "step_name": task_to_step.get(task_id, "unknown"),
                    "state": states[i] if i < len(states) else "PENDING",
                    "is_injected": False,
                }
                for i, task_id in enumerate(default_tasks[:5])
            ]
            failed_task_id = default_tasks[2] if len(default_tasks) > 2 else "unknown"
            schemas["UserFlowResponse"]["example"] = {
                "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "REJECTED",
                "total_tasks": len(default_tasks),
                "current_task_number": 3,
                "outcome": {
                    "failed_at_task": failed_task_id,
                    "reason": f"Application rejected at task: {failed_task_id}",
                },
                "tasks": flow_tasks_example,
            }

        # --- Dict-typed GET endpoints: patch path-level response examples ---
        paths = schema.get("paths", {})
        _patch_path_example(
            paths, "/api/v1/users/{user_id}/current", "get",
            {"current_step": task_step_name, "current_task": example_task.name},
        )
        _patch_path_example(
            paths, "/api/v1/users/{user_id}/status", "get",
            {"status": "IN_PROGRESS"},
        )

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _build_dynamic_openapi