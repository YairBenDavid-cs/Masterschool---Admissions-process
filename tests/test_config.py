import json
import pytest
from pathlib import Path
from pydantic import ValidationError

# We are importing from a file that might not be fully written yet - that's TDD!
from app.core.config import load_flow_config, Settings
from app.core.config_models import FlowConfig

def test_load_flow_config_success(tmp_path: Path):
    """
    Validates that load_flow_config correctly parses a valid JSON file
    when provided with a specific Settings dependency (Dependency Injection).
    """
    # Arrange: Create a temporary valid config file
    config_file = tmp_path / "test_flow.json"
    dummy_data = {
        "default_steps": ["step_1"],
        "tasks_map": {
            "test_task": {
                "name": "test_task",
                "pass_condition_type": "AUTO_PASS",
                "transitions": []
            }
        }
    }
    config_file.write_text(json.dumps(dummy_data))

    # Inject settings with the temporary path
    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act
    config = load_flow_config(settings=test_settings)

    # Assert
    assert isinstance(config, FlowConfig)
    assert "test_task" in config.tasks_map
    assert config.tasks_map["test_task"].name == "test_task"

def test_load_flow_config_file_not_found():
    """
    Validates that the loader raises FileNotFoundError when the 
    path in Settings does not exist.
    """
    # Arrange: Settings pointing to a non-existent file
    test_settings = Settings(FLOW_CONFIG_PATH="ghost_file.json")

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        load_flow_config(settings=test_settings)