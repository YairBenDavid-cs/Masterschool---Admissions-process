from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.config_models import FlowConfig
from app.core.logging_config import get_logger

# Initialize logger
logger = get_logger(__name__)

class Settings(BaseSettings):
    """
    Loads and validates the FSM blueprint from a JSON file.

    This function utilizes Dependency Injection by accepting the Settings 
    object, making it highly testable and decoupled from global state.

    Args:
        settings (Settings): The injected settings configuration containing 
                             the path to the JSON flow file.

    Returns:
        FlowConfig: The validated flow configuration blueprint parsed by Pydantic.

    Raises:
        FileNotFoundError: If the configuration file cannot be located at the specified path.
        RuntimeError: If the JSON parsing or Pydantic validation fails.
    """
    FLOW_CONFIG_PATH: str = "flow_config.json"
    PROJECT_NAME: str = "Masterschool Admissions Engine"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

def load_flow_config(settings: Settings) -> FlowConfig:
    """
    Loads and validates the FSM blueprint from a JSON file.
    """
    base_dir = Path(__file__).resolve().parent.parent.parent
    full_path = base_dir / settings.FLOW_CONFIG_PATH
    
    logger.info(f"Attempting to load configuration from: {full_path}")

    if not full_path.exists():
        error_msg = f"Critical error: Configuration file not found at {full_path}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            config_content = f.read()
            
        config = FlowConfig.model_validate_json(config_content)
        logger.info("FSM configuration loaded and validated successfully.")
        return config

    except Exception as exc:
        logger.critical(f"Failed to parse or validate FlowConfig: {exc}")
        raise RuntimeError("Core configuration initialization failed.") from exc

@lru_cache()
def get_settings() -> Settings:
    """
    Dependency provider that returns the application settings.
    Using @lru_cache ensures that the Settings object is instantiated only once (Singleton pattern).
    """
    return Settings()

@lru_cache()
def get_flow_config() -> FlowConfig:
    """
    Dependency provider that returns the loaded FSM configuration.
    Using @lru_cache ensures the JSON is parsed only once (Singleton pattern).
    """
    return load_flow_config(get_settings())