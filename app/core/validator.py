"""
Metadata-driven payload validation for FSM task blueprints.

Validates incoming task payloads against the payload_schema contract defined
in the JSON configuration. Adding a field to the JSON config automatically
starts enforcing it here — zero Python changes required.
"""

from typing import Any, Dict

from app.core.config_models import TaskBlueprint
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Maps JSON config type strings to Python runtime types
_PYTHON_TYPE_MAP: dict[str, type] = {
    "int": int,
    "str": str,
    "float": float,
    "bool": bool,
}


class PayloadValidationError(Exception):
    """Raised when a task payload violates the blueprint's payload_schema contract."""
    pass


def validate_task_payload(payload: Dict[str, Any], task_blueprint: TaskBlueprint) -> None:
    """
    Validates the payload against the task blueprint's declared payload_schema.

    This is a no-op when payload_schema is empty (backward compatible with tasks
    that have no schema defined). Iterates through each FieldDefinition and enforces
    presence and type constraints.

    Args:
        payload (Dict[str, Any]): The incoming task payload submitted by the client.
        task_blueprint (TaskBlueprint): The FSM task blueprint containing the schema contract.

    Returns:
        None

    Raises:
        PayloadValidationError: On the first violated field — either missing required
            field or incorrect type.
    """
    if not task_blueprint.payload_schema:
        return  # No contract defined; skip validation (backward compatible)

    for field_def in task_blueprint.payload_schema:
        # 1. Check required presence
        if field_def.required and field_def.key_name not in payload:
            msg = (
                f"Task '{task_blueprint.name}' requires field '{field_def.key_name}' "
                f"(type: {field_def.value_type}) but it was not provided."
            )
            logger.warning(msg)
            raise PayloadValidationError(msg)

        # 2. Type check when field is present
        if field_def.key_name in payload:
            expected_type = _PYTHON_TYPE_MAP.get(field_def.value_type)
            if expected_type and not isinstance(payload[field_def.key_name], expected_type):
                actual_type = type(payload[field_def.key_name]).__name__
                msg = (
                    f"Task '{task_blueprint.name}': field '{field_def.key_name}' must be "
                    f"'{field_def.value_type}', got '{actual_type}'."
                )
                logger.warning(msg)
                raise PayloadValidationError(msg)
