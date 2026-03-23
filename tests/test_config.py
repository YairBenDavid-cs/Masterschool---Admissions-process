import json
import pytest
from pathlib import Path

from app.core.config import load_flow_config, Settings
from app.core.config_models import FlowConfig

def test_load_flow_config_success(tmp_path: Path):
    """
    Validates that load_flow_config correctly parses a valid JSON file
    that strictly aligns with the actual production schema.
    """
    # Arrange: Create a temporary valid config file
    config_file = tmp_path / "test_flow.json"
    
    # EXACT SCHEMA MATCH: default_steps is a list of objects, not strings.
    dummy_data = {
        "default_steps": [
            {
                "name": "personal_details",
                "display_name": "Personal Details Form",
                "tasks": ["submit_personal_details"]
            }
        ],
        "tasks_map": {
            "submit_personal_details": {
                "name": "submit_personal_details",
                "pass_condition_type": "AUTO_PASS",
                "transitions": [
                    {
                        "condition": "DEFAULT",
                        "next_step": "iq_test",
                        "next_task": "perform_iq_test"
                    }
                ]
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
    
    # Validate the Steps object structure
    assert len(config.default_steps) == 1
    assert config.default_steps[0].name == "personal_details"
    assert config.default_steps[0].tasks == ["submit_personal_details"]
    
    # Validate the Tasks Map structure
    assert "submit_personal_details" in config.tasks_map
    assert config.tasks_map["submit_personal_details"].transitions[0].next_step == "iq_test"

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