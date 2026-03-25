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
A **Data-Driven Finite State Machine** API for the Masterschool candidate enrollment process.

All flow logic lives in `flow_config.json`. The Python engine is 100% domain-agnostic and fully PM-configurable without code changes.

---

## Quick Start Guide

Follow these steps in order to run a complete admissions flow directly from this UI:

### Step 1 — Register a Candidate
**`POST /api/v1/users`** — Click **Try it out**, then **Execute**.
The email is pre-filled and ready to go.
Copy the `user_id` from the response body.

### Step 2 — Advance Through the Flow
**`PUT /api/v1/tasks/complete`** — Click **Try it out**, paste your `user_id` into the request body, and click **Execute**.
The `current_step` and `current_task` are pre-filled with the first step of the flow.
Each response returns the **next** `current_step` and `current_task` — update the body and repeat until `status` is `ACCEPTED` or `REJECTED`.

### Step 3 — Poll the Outcome at Any Time
**`GET /api/v1/users/{user_id}/status`** — Paste your `user_id` to check the candidate's final admission decision.

---

**Full Flow:** `Personal Details → IQ Test → Interview → Sign Contract → Payment → Join Slack → ACCEPTED`
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

        # --- UserFlowResponse: realistic mid-flow snapshot ---
        if "UserFlowResponse" in schemas:
            default_tasks = [task for step in flow.default_steps for task in step.tasks]
            states = ["COMPLETED", "COMPLETED", "CURRENT", "PENDING", "PENDING"]
            flow_tasks_example = [
                {
                    "task_id": task_id,
                    "state": states[i] if i < len(states) else "PENDING",
                    "is_injected": False,
                }
                for i, task_id in enumerate(default_tasks[:5])
            ]
            schemas["UserFlowResponse"]["example"] = {
                "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "IN_PROGRESS",
                "total_tasks": len(default_tasks),
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