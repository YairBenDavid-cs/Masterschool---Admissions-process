"""Tests for the underlying FSM system, routing, and agnostic flow mechanics."""

import json
import pytest
from pathlib import Path
from pydantic import ValidationError

pytestmark = pytest.mark.system

from app.core.config import load_flow_config, Settings
from app.core.config_models import FlowConfig, PassConditionType


# =============================================================================
# 1. Successful Loading & Decoupling
# =============================================================================

def test_load_flow_config_success(tmp_path: Path):
    """
    [Layer A] Validates that load_flow_config correctly parses a valid JSON file.

    Decoupling Focus: We use generic names ('step_alpha', 'task_x') instead of
    domain-specific names ('iq_test') to prove the loader is purely structural
    and data-driven, agnostic to the actual business flow.

    Args:
        tmp_path (Path): Pytest-provided temporary directory for file creation.

    Expected Behavior:
        The returned FlowConfig contains the expected step, task, enum values,
        and inject_to_custom_flow flag, all correctly parsed from JSON.
    """
    # Arrange — Create a temporary valid config file with dynamic flag included
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
    assert len(config.default_steps) == 1
    assert config.default_steps[0].name == "step_alpha"

    parsed_task = config.tasks_map["task_x"]
    assert parsed_task.pass_condition_type == PassConditionType.EVALUATE_PAYLOAD
    assert parsed_task.transitions[0].next_step == "step_beta"
    assert parsed_task.transitions[0].inject_to_custom_flow is True


# =============================================================================
# 2. Negative Testing (File System Errors)
# =============================================================================

def test_load_flow_config_file_not_found():
    """
    [Layer A] Validates that the loader raises FileNotFoundError when the
    path in Settings points to a non-existent file.

    Expected Behavior:
        FileNotFoundError is raised immediately, preventing any downstream
        parsing attempts on a missing file.
    """
    # Arrange — Settings pointing to a ghost file
    test_settings = Settings(FLOW_CONFIG_PATH="ghost_file.json")

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        load_flow_config(settings=test_settings)


# =============================================================================
# 3. Negative Testing (Schema & Enum Validation Errors)
# =============================================================================

def test_load_flow_config_missing_field_error(tmp_path: Path):
    """
    [Layer A] Validates that the loader raises a RuntimeError if the
    JSON file is structurally invalid (e.g., missing required fields).

    Technical Excellence: Ensures corrupted FSM configurations crash early
    and explicitly, rather than causing downstream logic errors.

    Args:
        tmp_path (Path): Pytest-provided temporary directory for file creation.

    Expected Behavior:
        RuntimeError is raised when the JSON is missing the required
        'tasks_map' field, wrapping the underlying Pydantic validation error.
    """
    # Arrange — Create a malformed config file (missing 'tasks_map')
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
    [Layer A] Validates that Pydantic strictly enforces Enum values.
    If the JSON contains an invalid pass_condition_type, it must fail early.

    Args:
        tmp_path (Path): Pytest-provided temporary directory for file creation.

    Expected Behavior:
        RuntimeError is raised with the underlying cause referencing the
        invalid enum value 'MAGIC_PASS'.
    """
    # Arrange — Valid structure, but invalid Enum value
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

    assert "MAGIC_PASS" in str(exc_info.value.__cause__)


# =============================================================================
# 4. Schema Resilience & Edge Case Tests
# =============================================================================

def test_inject_to_custom_flow_defaults_to_false(tmp_path: Path):
    """
    [Layer A] Validates that inject_to_custom_flow defaults to False when omitted from JSON.

    Pydantic models should apply their default field values when the JSON
    does not explicitly include the field. This ensures backward compatibility
    when new fields are added to the schema.

    Args:
        tmp_path (Path): Pytest-provided temporary directory for file creation.

    Expected Behavior:
        A transition without inject_to_custom_flow in the JSON has the
        field set to False by Pydantic's default.
    """
    # Arrange — JSON with no inject_to_custom_flow key on the transition
    config_file = tmp_path / "no_inject_flag.json"

    data = {
        "default_steps": [
            {
                "name": "step_one",
                "display_name": "Step One",
                "tasks": ["task_one"]
            }
        ],
        "tasks_map": {
            "task_one": {
                "name": "task_one",
                "pass_condition_type": "AUTO_PASS",
                "transitions": [
                    {
                        "condition": "DEFAULT",
                        "next_step": "step_two",
                        "next_task": "task_two"
                    }
                ]
            }
        }
    }
    config_file.write_text(json.dumps(data))
    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act
    config = load_flow_config(settings=test_settings)

    # Assert
    transition = config.tasks_map["task_one"].transitions[0]
    assert transition.inject_to_custom_flow is False

def test_load_flow_config_with_extra_json_fields(tmp_path: Path):
    """
    [Layer A] Validates that extra unknown fields in the JSON are silently ignored.

    Pydantic V2's default behavior ignores extra fields not defined in the
    model schema. This ensures forward compatibility when the JSON evolves
    faster than the Python models (e.g., a PM adds metadata fields).

    Args:
        tmp_path (Path): Pytest-provided temporary directory for file creation.

    Expected Behavior:
        No exception is raised despite extra top-level and task-level fields.
        The returned FlowConfig is valid and correctly typed.
    """
    # Arrange — JSON with extra unknown fields at multiple levels
    config_file = tmp_path / "extra_fields.json"

    data = {
        "default_steps": [
            {
                "name": "step_one",
                "display_name": "Step One",
                "tasks": ["task_one"]
            }
        ],
        "tasks_map": {
            "task_one": {
                "name": "task_one",
                "pass_condition_type": "AUTO_PASS",
                "description": "This field is not in the Pydantic model",
                "transitions": [
                    {
                        "condition": "DEFAULT",
                        "next_step": "step_two",
                        "next_task": "task_two",
                        "some_future_flag": True
                    }
                ]
            }
        },
        "metadata": {"version": "2.0", "author": "PM Team"}
    }
    config_file.write_text(json.dumps(data))
    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act
    config = load_flow_config(settings=test_settings)

    # Assert
    assert isinstance(config, FlowConfig)
    assert len(config.default_steps) == 1
    assert "task_one" in config.tasks_map

def test_load_flow_config_empty_default_steps_is_valid(tmp_path: Path):
    """
    [Layer A] Validates that an empty default_steps list passes schema validation.

    The Pydantic schema allows zero steps because business logic enforcement
    (requiring at least one step) is the responsibility of the service layer,
    not the configuration parser. This separation of concerns ensures the
    loader remains purely structural.

    Args:
        tmp_path (Path): Pytest-provided temporary directory for file creation.

    Expected Behavior:
        FlowConfig is returned with an empty default_steps list and no exception.
    """
    # Arrange — Valid JSON structure with empty steps list
    config_file = tmp_path / "empty_steps.json"

    data = {
        "default_steps": [],
        "tasks_map": {
            "orphan_task": {
                "name": "orphan_task",
                "pass_condition_type": "AUTO_PASS",
                "transitions": [
                    {
                        "condition": "DEFAULT",
                        "next_step": "TERMINAL_ACCEPTED",
                        "next_task": "NONE"
                    }
                ]
            }
        }
    }
    config_file.write_text(json.dumps(data))
    test_settings = Settings(FLOW_CONFIG_PATH=str(config_file))

    # Act
    config = load_flow_config(settings=test_settings)

    # Assert
    assert isinstance(config, FlowConfig)
    assert len(config.default_steps) == 0
