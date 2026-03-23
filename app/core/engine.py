from typing import Any, Dict, Optional
from app.core.config_models import TaskBlueprint, TransitionRule, PassConditionType
from app.core.logging_config import get_logger

# Initialize logger for the engine module
logger = get_logger(__name__)

class EngineEvaluationError(Exception):
    """Custom exception raised when the FSM engine fails to evaluate a transition."""
    pass

def evaluate_transition(task_blueprint: TaskBlueprint, payload: Dict[str, Any]) -> TransitionRule:
    """
    Evaluates the transition rules for a given task based on the provided payload.

    This function acts as the core decision-making engine of the FSM. It processes 
    rules sequentially and safely evaluates dynamic python-based conditions defined 
    in the JSON configuration.

    Args:
        task_blueprint (TaskBlueprint): The configuration blueprint of the current task.
        payload (Dict[str, Any]): The dynamic data submitted by the user or webhook.

    Returns:
        TransitionRule: The specific transition rule that the user matched.

    Raises:
        EngineEvaluationError: If the task has no transitions or no DEFAULT fallback is found.
    """
    logger.debug(f"Evaluating transitions for task: {task_blueprint.name}")

    # Guard Clause 1: Ensure transitions exist
    if not task_blueprint.transitions:
        error_msg = f"Task '{task_blueprint.name}' has no defined transitions."
        logger.error(error_msg)
        raise EngineEvaluationError(error_msg)

    # Guard Clause 2: Handle AUTO_PASS immediately (Early Return)
    if task_blueprint.pass_condition_type == PassConditionType.AUTO_PASS:
        logger.debug(f"Task '{task_blueprint.name}' is AUTO_PASS. Bypassing payload evaluation.")
        return _get_default_transition(task_blueprint)

    # Evaluate dynamic conditions for EVALUATE_PAYLOAD
    for rule in task_blueprint.transitions:
        if rule.condition == "DEFAULT":
            continue  # Skip DEFAULT during the main evaluation loop

        logger.debug(f"Evaluating condition: {rule.condition}")
        
        if _evaluate_condition_safely(condition=rule.condition, payload=payload):
            logger.info(f"Condition met for task '{task_blueprint.name}'. Transitioning to: {rule.next_task}")
            return rule

    # Fallback to DEFAULT if no specific conditions were met
    logger.info(f"No specific conditions met for '{task_blueprint.name}'. Falling back to DEFAULT.")
    return _get_default_transition(task_blueprint)


def _get_default_transition(task_blueprint: TaskBlueprint) -> TransitionRule:
    """
    Extracts the 'DEFAULT' transition rule from a task blueprint.

    Args:
        task_blueprint (TaskBlueprint): The task configuration.

    Returns:
        TransitionRule: The default transition rule.

    Raises:
        EngineEvaluationError: If no DEFAULT rule is explicitly defined in the task.
    """
    for rule in task_blueprint.transitions:
        if rule.condition == "DEFAULT":
            return rule
            
    error_msg = f"Task '{task_blueprint.name}' is missing a mandatory 'DEFAULT' transition rule."
    logger.critical(error_msg)
    raise EngineEvaluationError(error_msg)


def _evaluate_condition_safely(condition: str, payload: Dict[str, Any]) -> bool:
    """
    Safely executes a dynamic Python string condition against a local payload dictionary.

    Utilizes a restricted evaluation environment to prevent code injection. Only the 
    'payload' variable is exposed to the condition string.

    Args:
        condition (str): The python-evaluable string (e.g., "payload.get('score') > 75").
        payload (Dict[str, Any]): The data to evaluate against.

    Returns:
        bool: True if the condition evaluates to truthy, False otherwise.
    """
    # Restrict the execution environment for security
    allowed_globals = {"__builtins__": {}}
    allowed_locals = {"payload": payload}

    try:
        # Evaluate the string as a Python expression
        result = eval(condition, allowed_globals, allowed_locals)
        return bool(result)
    except Exception as exc:
        logger.error(f"Failed to safely evaluate condition '{condition}': {exc}")
        # If a condition throws an error (e.g., missing key and no .get() used), 
        # it is treated as a failed condition, not a system crash.
        return False