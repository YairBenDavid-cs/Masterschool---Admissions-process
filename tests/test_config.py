import json
import pytest
from pathlib import Path
from pydantic import ValidationError

from app.core.config import load_flow_config, Settings
from app.core.config_models import FlowConfig, PassConditionType

# --- 1. Successful Loading & Decoupling ---

def test_load_flow_config_success(tmp_path: Path):
    """
    Validates that load_flow_config correctly parses a valid JSON file.
    
    Decoupling Focus: We use generic names ('step_alpha', 'task_x') instead of 
    domain-specific names ('iq_test') to prove the loader is purely structural 
    and data-driven, agnostic to the actual business flow.
    """
    # Arrange: Create a temporary valid config file with dynamic flag included
    config_file = tmp_path / "dynamic_flow.json"
    
    dummy_data = {
        "default_steps": [
            {
                "name": "step_alpha",
                "display_name": "First Step",
                "tasks": ["task_x"]
            }
        ],
        "tasks_map": {
            "task_x": {
                "name": "task_x",
                "pass_condition_type": "EVALUATE_PAYLOAD",
                "transitions": [
                    {
                        "condition": "DEFAULT",
                        "next_step": "step_beta",
                        "next_task": "task_y",
                        "inject_to_custom_flow": True  
                    }
                ]
            }
        }
    }
    config_file.write_text(json.dumps(dummy_data))

    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act
    config = load_flow_config(settings=test_settings)

    # Assert
    assert isinstance(config, FlowConfig)
    
    # Validate the Steps object structure
    assert len(config.default_steps) == 1
    assert config.default_steps[0].name == "step_alpha"
    
    # Validate the Tasks Map structure and our specific Enum/Boolean parsers
    parsed_task = config.tasks_map["task_x"]
    assert parsed_task.pass_condition_type == PassConditionType.EVALUATE_PAYLOAD
    assert parsed_task.transitions[0].next_step == "step_beta"
    assert parsed_task.transitions[0].inject_to_custom_flow is True


# --- 2. Negative Testing (File System Errors) ---

def test_load_flow_config_file_not_found():
    """
    Validates that the loader raises FileNotFoundError when the 
    path in Settings points to a non-existent file.
    """
    # Arrange: Settings pointing to a ghost file
    test_settings = Settings(FLOW_CONFIG_PATH="ghost_file.json")

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        load_flow_config(settings=test_settings)


# --- 3. Negative Testing (Schema & Enum Validation Errors) ---

def test_load_flow_config_missing_field_error(tmp_path: Path):
    """
    Validates that the loader raises a RuntimeError if the 
    JSON file is structurally invalid (e.g., missing required fields).
    
    Technical Excellence: Ensures corrupted FSM configurations crash early 
    and explicitly, rather than causing downstream logic errors.
    """
    # Arrange: Create a malformed config file (missing 'tasks_map')
    config_file = tmp_path / "broken_flow.json"
    
    corrupted_data = {
        "default_steps": [
            {
                "name": "step_alpha",
                "display_name": "First Step",
                "tasks": ["task_x"]
            }
        ]
        # MISSING tasks_map completely
    }
    config_file.write_text(json.dumps(corrupted_data))

    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act & Assert
    with pytest.raises(RuntimeError):
        load_flow_config(settings=test_settings)

def test_load_flow_config_invalid_enum_error(tmp_path: Path):
    """
    Validates that Pydantic strictly enforces Enum values.
    If the JSON contains an invalid pass_condition_type, it must fail early.
    """
    # Arrange: Valid structure, but invalid Enum value
    config_file = tmp_path / "invalid_enum_flow.json"
    
    invalid_enum_data = {
        "default_steps": [
            {
                "name": "step_alpha",
                "display_name": "First Step",
                "tasks": ["task_x"]
            }
        ],
        "tasks_map": {
            "task_x": {
                "name": "task_x",
                "pass_condition_type": "MAGIC_PASS",  # Invalid Enum Value!
                "transitions": [
                    {
                        "condition": "DEFAULT",
                        "next_step": "TERMINAL_REJECTED",
                        "next_task": "NONE"
                    }
                ]
            }
        }
    }
    config_file.write_text(json.dumps(invalid_enum_data))

    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act & Assert
    with pytest.raises(RuntimeError) as exc_info:
        load_flow_config(settings=test_settings)
        
    # Assert that the error is specifically about the bad Enum value
    assert "MAGIC_PASS" in str(exc_info.value.__cause__)