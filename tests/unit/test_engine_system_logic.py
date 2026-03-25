"""Tests for the underlying FSM system, routing, and agnostic flow mechanics."""

import pytest
from typing import Dict, Any

pytestmark = pytest.mark.system

from app.core.config_models import TaskBlueprint, TransitionRule, Status, PassConditionType
from app.core.engine import evaluate_transition, EngineEvaluationError

# =============================================================================
# FIXTURES (Decoupled & Generic)
# =============================================================================

@pytest.fixture
def numeric_eval_blueprint() -> TaskBlueprint:
    """
    Provides a TaskBlueprint for testing numeric threshold evaluations.

    Returns:
        TaskBlueprint: A blueprint containing greater-than, range-based,
        and default fallback transitions, including an Approach 3 injection flag.
    """
    return TaskBlueprint(
        name="numeric_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('score', 0) > 75",
                next_step="step_success",
                next_task="task_success"
            ),
            TransitionRule(
                condition="payload.get('score', 0) >= 60 and payload.get('score', 0) <= 75",
                next_step="step_current",
                next_task="task_injection",
                inject_to_custom_flow=True  # Approach 3 Data-Driven Flag
            ),
            TransitionRule(
                condition="DEFAULT",
                next_step="TERMINAL_REJECTED",
                next_task="NONE",
                mark_status=Status.REJECTED
            )
        ]
    )

@pytest.fixture
def string_eval_blueprint() -> TaskBlueprint:
    """
    Provides a TaskBlueprint for testing exact string matching evaluations.

    Returns:
        TaskBlueprint: A blueprint containing a strict string equality check
        and a default fallback transition.
    """
    return TaskBlueprint(
        name="string_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('decision') == 'approved'",
                next_step="step_next",
                next_task="task_next"
            ),
            TransitionRule(
                condition="DEFAULT",
                next_step="TERMINAL_REJECTED",
                next_task="NONE",
                mark_status=Status.REJECTED
            )
        ]
    )

@pytest.fixture
def auto_pass_blueprint() -> TaskBlueprint:
    """
    Provides a standard AUTO_PASS task behavior configuration.

    Returns:
        TaskBlueprint: A blueprint that should bypass payload evaluation
        entirely and return the default transition.
    """
    return TaskBlueprint(
        name="auto_task",
        pass_condition_type=PassConditionType.AUTO_PASS,
        transitions=[
            TransitionRule(
                condition="DEFAULT",
                next_step="step_next",
                next_task="task_next"
            )
        ]
    )

@pytest.fixture
def corrupted_eval_blueprint() -> TaskBlueprint:
    """
    Provides a TaskBlueprint containing invalid Python syntax.

    Returns:
        TaskBlueprint: A blueprint explicitly designed to fail the eval()
        function due to a missing parenthesis, forcing a safe DEFAULT fallback.
    """
    return TaskBlueprint(
        name="corrupted_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('score' > 75",  # SYNTAX ERROR
                next_step="step_next",
                next_task="task_next"
            ),
            TransitionRule(
                condition="DEFAULT",
                next_step="TERMINAL_REJECTED",
                next_task="NONE",
                mark_status=Status.REJECTED
            )
        ]
    )

@pytest.fixture
def no_transitions_blueprint() -> TaskBlueprint:
    """
    Provides a TaskBlueprint with an empty transitions list.

    This fixture is designed to trigger the engine's guard clause that
    validates transitions exist before attempting evaluation.

    Returns:
        TaskBlueprint: A blueprint with zero transition rules defined.
    """
    return TaskBlueprint(
        name="empty_transitions_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[]
    )

@pytest.fixture
def no_default_blueprint() -> TaskBlueprint:
    """
    Provides a TaskBlueprint with only an unmatchable condition and no DEFAULT rule.

    This fixture is designed to trigger the engine's guard clause that
    validates a DEFAULT fallback exists when no conditions match.

    Returns:
        TaskBlueprint: A blueprint with a single condition that will never
            match (score > 999), and no DEFAULT transition.
    """
    return TaskBlueprint(
        name="no_default_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('score', 0) > 999",
                next_step="step_unreachable",
                next_task="task_unreachable"
            )
        ]
    )

@pytest.fixture
def boolean_eval_blueprint() -> TaskBlueprint:
    """
    Provides a TaskBlueprint with a boolean equality condition.

    Tests that the engine can evaluate non-numeric, non-string conditions
    such as boolean comparisons against payload values.

    Returns:
        TaskBlueprint: A blueprint with a True equality check and a
            DEFAULT fallback transition.
    """
    return TaskBlueprint(
        name="boolean_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('approved') == True",
                next_step="step_approved",
                next_task="task_approved"
            ),
            TransitionRule(
                condition="DEFAULT",
                next_step="TERMINAL_REJECTED",
                next_task="NONE",
                mark_status=Status.REJECTED
            )
        ]
    )


# =============================================================================
# 1. NUMERIC & LOGICAL EVALUATION TESTS
# =============================================================================

def test_engine_numeric_condition_success(numeric_eval_blueprint: TaskBlueprint) -> None:
    """
    Validates that the engine correctly evaluates a 'greater than' numeric condition.

    Args:
        numeric_eval_blueprint (TaskBlueprint): The numeric logic fixture.

    Expected Behavior:
        The engine evaluates the payload (82 > 75), selects the first transition,
        and leaves the custom flow injection flag as False.
    """
    # Arrange
    payload: Dict[str, Any] = {"score": 82}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=numeric_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "step_success"
    assert rule.next_task == "task_success"
    assert rule.mark_status is None
    assert rule.inject_to_custom_flow is False

def test_engine_numeric_condition_injection_flag(numeric_eval_blueprint: TaskBlueprint) -> None:
    """
    Validates the dynamic injection (Approach 3) flag preservation.

    Args:
        numeric_eval_blueprint (TaskBlueprint): The numeric logic fixture.

    Expected Behavior:
        The engine matches the mid-range condition (60-75) and correctly
        returns the TransitionRule with `inject_to_custom_flow=True`.
    """
    # Arrange
    payload: Dict[str, Any] = {"score": 65}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=numeric_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "step_current"
    assert rule.next_task == "task_injection"
    assert rule.inject_to_custom_flow is True

def test_engine_numeric_condition_default_fallback(numeric_eval_blueprint: TaskBlueprint) -> None:
    """
    Validates that failing all specific conditions safely triggers the DEFAULT fallback.

    Args:
        numeric_eval_blueprint (TaskBlueprint): The numeric logic fixture.

    Expected Behavior:
        Since the score (55) matches no specific rules, the engine defaults
        to the terminal rejection state.
    """
    # Arrange
    payload: Dict[str, Any] = {"score": 55}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=numeric_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "TERMINAL_REJECTED"
    assert rule.next_task == "NONE"
    assert rule.mark_status == Status.REJECTED


# =============================================================================
# 2. STRING EVALUATION TESTS
# =============================================================================

def test_engine_string_condition_match(string_eval_blueprint: TaskBlueprint) -> None:
    """
    Validates that the engine correctly evaluates exact string matches in the payload.

    Args:
        string_eval_blueprint (TaskBlueprint): The string logic fixture.

    Expected Behavior:
        The engine matches the string equality ('approved') and advances the state.
    """
    # Arrange
    payload: Dict[str, Any] = {"decision": "approved"}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=string_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "step_next"
    assert rule.next_task == "task_next"
    assert rule.mark_status is None

def test_engine_string_condition_mismatch(string_eval_blueprint: TaskBlueprint) -> None:
    """
    Validates that mismatched strings bypass specific rules and hit the DEFAULT rule.

    Args:
        string_eval_blueprint (TaskBlueprint): The string logic fixture.

    Expected Behavior:
        An unmapped string ('denied') falls through to the terminal rejection state.
    """
    # Arrange
    payload: Dict[str, Any] = {"decision": "denied"}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=string_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "TERMINAL_REJECTED"
    assert rule.next_task == "NONE"
    assert rule.mark_status == Status.REJECTED


# =============================================================================
# 3. AUTO_PASS TESTS
# =============================================================================

def test_engine_auto_pass_ignores_payload(auto_pass_blueprint: TaskBlueprint) -> None:
    """
    Validates that AUTO_PASS tasks bypass payload evaluation entirely.

    Args:
        auto_pass_blueprint (TaskBlueprint): The auto-pass logic fixture.

    Expected Behavior:
        Regardless of the payload content, the engine immediately selects
        the DEFAULT transition.
    """
    # Arrange
    payload: Dict[str, Any] = {"some_garbage_data": True}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=auto_pass_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "step_next"
    assert rule.next_task == "task_next"


# =============================================================================
# 4. NEGATIVE TESTING & RESILIENCE (SECURITY)
# =============================================================================

def test_engine_handles_corrupted_syntax(corrupted_eval_blueprint: TaskBlueprint) -> None:
    """
    Validates engine resilience against malformed transition conditions.

    Args:
        corrupted_eval_blueprint (TaskBlueprint): The corrupted syntax fixture.

    Expected Behavior:
        The engine catches the Python SyntaxError internally, treats the
        corrupted condition as False, and safely falls back to the DEFAULT rule
        to prevent a fatal application crash.
    """
    # Arrange
    payload: Dict[str, Any] = {"score": 100}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=corrupted_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "TERMINAL_REJECTED"
    assert rule.next_task == "NONE"
    assert rule.mark_status == Status.REJECTED


# =============================================================================
# 5. GUARD CLAUSE & RESILIENCE TESTS
# =============================================================================

def test_engine_raises_when_no_transitions(no_transitions_blueprint: TaskBlueprint) -> None:
    """
    [Layer A] Validates that the engine raises when a task has zero transition rules.

    The engine's first guard clause checks for an empty transitions list
    and raises immediately, preventing any evaluation logic from executing
    on an unconfigured task.

    Args:
        no_transitions_blueprint (TaskBlueprint): A blueprint with an empty
            transitions list.

    Expected Behavior:
        EngineEvaluationError is raised before any condition evaluation
        is attempted, with a message referencing the task name.
    """
    # Arrange
    payload: Dict[str, Any] = {}

    # Act & Assert
    with pytest.raises(EngineEvaluationError):
        evaluate_transition(task_blueprint=no_transitions_blueprint, payload=payload)

def test_engine_raises_when_no_default_rule(no_default_blueprint: TaskBlueprint) -> None:
    """
    [Layer A] Validates that the engine raises when all conditions fail and no DEFAULT exists.

    When the engine exhausts all conditional rules without a match and
    cannot find a DEFAULT fallback, it must raise rather than silently
    returning None or an undefined state.

    Args:
        no_default_blueprint (TaskBlueprint): A blueprint with only an
            unmatchable condition (score > 999) and no DEFAULT rule.

    Expected Behavior:
        EngineEvaluationError is raised because the payload (score=50)
        does not match the impossible condition and no DEFAULT exists.
    """
    # Arrange
    payload: Dict[str, Any] = {"score": 50}

    # Act & Assert
    with pytest.raises(EngineEvaluationError):
        evaluate_transition(task_blueprint=no_default_blueprint, payload=payload)

def test_engine_none_value_in_payload_treated_as_fallthrough(numeric_eval_blueprint: TaskBlueprint) -> None:
    """
    [Layer A] Validates that a None value in the payload falls through to DEFAULT.

    When the payload key exists but its value is None, payload.get('score', 0)
    returns None (not 0, because the key exists). Comparing None > 75 or
    checking None in range raises a TypeError, which the engine's
    _evaluate_condition_safely catches and treats as False.

    Args:
        numeric_eval_blueprint (TaskBlueprint): The numeric logic fixture with
            greater-than, range, and DEFAULT transitions.

    Expected Behavior:
        All conditional rules fail silently (TypeError caught internally),
        and the engine falls through to the DEFAULT rule (TERMINAL_REJECTED).
    """
    # Arrange
    payload: Dict[str, Any] = {"score": None}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=numeric_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "TERMINAL_REJECTED"
    assert rule.next_task == "NONE"
    assert rule.mark_status == Status.REJECTED

def test_engine_boolean_condition_match(boolean_eval_blueprint: TaskBlueprint) -> None:
    """
    [Layer A] Validates that a boolean equality condition evaluates correctly.

    The engine must support non-numeric condition types including boolean
    comparisons. When the payload contains approved=True, the condition
    'payload.get("approved") == True' should match.

    Args:
        boolean_eval_blueprint (TaskBlueprint): A blueprint with a boolean
            equality condition and a DEFAULT fallback.

    Expected Behavior:
        The engine matches the True condition and returns the approved
        transition rule, bypassing the DEFAULT.
    """
    # Arrange
    payload: Dict[str, Any] = {"approved": True}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=boolean_eval_blueprint, payload=payload)

    # Assert
    assert rule.next_step == "step_approved"
    assert rule.next_task == "task_approved"
    assert rule.mark_status is None

def test_engine_first_matching_condition_wins() -> None:
    """
    [Layer A] Validates that the engine returns the FIRST matching condition in sequence.

    Transition rules are evaluated in order. When multiple conditions would
    match the same payload, the engine must return the first match immediately
    without evaluating subsequent rules. This guarantees deterministic
    behavior based on rule ordering in the configuration.

    Expected Behavior:
        A payload with score=80 matches both 'score > 50' and 'score > 30',
        but the engine returns 'first_match' because it appears first in
        the transitions list.
    """
    # Arrange
    blueprint: TaskBlueprint = TaskBlueprint(
        name="priority_task",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('score', 0) > 50",
                next_step="step_first",
                next_task="first_match"
            ),
            TransitionRule(
                condition="payload.get('score', 0) > 30",
                next_step="step_second",
                next_task="second_match"
            ),
            TransitionRule(
                condition="DEFAULT",
                next_step="step_default",
                next_task="default_match"
            )
        ]
    )
    payload: Dict[str, Any] = {"score": 80}

    # Act
    rule: TransitionRule = evaluate_transition(task_blueprint=blueprint, payload=payload)

    # Assert
    assert rule.next_task == "first_match"
    assert rule.next_step == "step_first"
