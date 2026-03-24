import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Router import
from app.api.routes import router as api_router

# Configuration and Core imports
from app.core.config import load_flow_config, Settings
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
# FASTAPI APPLICATION INSTANCE
# =============================================================================
app = FastAPI(
    title="Masterschool Admissions Engine",
    description="A Data-Driven Finite State Machine API for candidate enrollment.",
    version="1.0.0",
    docs_url="/docs",   # Swagger UI
    redoc_url="/redoc"  # ReDoc UI
)

# Mount the API routes defined in app/api/routes.py
app.include_router(api_router)


# =============================================================================
# LIFECYCLE EVENTS
# =============================================================================
@app.on_event("startup")
async def startup_event() -> None:
    """
    Executes on application startup.
    
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
@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    """
    Liveness probe endpoint.
    Used by container orchestration tools (like Docker Compose or Kubernetes) 
    to verify the application process is running and responsive.
    
    Returns:
        dict: A simple health status indicator.
    """
    return {"status": "healthy"}