import pytest
from typing import Dict, Any
from app.core.config_models import TaskBlueprint, TransitionRule, Status, PassConditionType
from app.core.engine import evaluate_transition

@pytest.fixture
def iq_task_blueprint() -> TaskBlueprint:
    """
    Fixture providing the exact blueprint for the IQ Test task 
    from the Masterschool flow configuration.
    """
    return TaskBlueprint(
        name="perform_iq_test",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('score', 0) > 75",
                next_step="interview",
                next_task="schedule_interview"
            ),
            TransitionRule(
                condition="payload.get('score', 0) >= 60 and payload.get('score', 0) <= 75",
                next_step="iq_test",
                next_task="second_chance_iq"
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
def interview_task_blueprint() -> TaskBlueprint:
    """
    Fixture providing the blueprint for the interview evaluation task.
    """
    return TaskBlueprint(
        name="perform_interview",
        pass_condition_type=PassConditionType.EVALUATE_PAYLOAD,
        transitions=[
            TransitionRule(
                condition="payload.get('decision') == 'passed_interview'",
                next_step="sign_contract",
                next_task="upload_identification_document"
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
def auto_pass_task_blueprint() -> TaskBlueprint:
    """
    Fixture providing a standard AUTO_PASS task (like submit_personal_details).
    """
    return TaskBlueprint(
        name="submit_personal_details",
        pass_condition_type=PassConditionType.AUTO_PASS,
        transitions=[
            TransitionRule(
                condition="DEFAULT",
                next_step="iq_test",
                next_task="perform_iq_test"
            )
        ]
    )

# --- IQ Test Scenarios ---

def test_evaluate_transition_iq_high_score(iq_task_blueprint: TaskBlueprint) -> None:
    """
    Validates that a high IQ score (>75) moves the candidate to the interview step.
    """
    payload: Dict[str, Any] = {"score": 82}
    
    rule = evaluate_transition(task_blueprint=iq_task_blueprint, payload=payload)
    
    assert rule.next_step == "interview"
    assert rule.next_task == "schedule_interview"
    assert rule.mark_status is None

def test_evaluate_transition_iq_medium_score(iq_task_blueprint: TaskBlueprint) -> None:
    """
    Validates the PM's edge case: A score between 60 and 75 triggers 
    the hidden 'second_chance_iq' task without failing the candidate.
    """
    payload: Dict[str, Any] = {"score": 65}
    
    rule = evaluate_transition(task_blueprint=iq_task_blueprint, payload=payload)
    
    assert rule.next_step == "iq_test"
    assert rule.next_task == "second_chance_iq"
    assert rule.mark_status is None

def test_evaluate_transition_iq_low_score(iq_task_blueprint: TaskBlueprint) -> None:
    """
    Validates that a low IQ score (<60) hits the DEFAULT fallback and rejects the candidate.
    """
    payload: Dict[str, Any] = {"score": 55}
    
    rule = evaluate_transition(task_blueprint=iq_task_blueprint, payload=payload)
    
    assert rule.next_step == "TERMINAL_REJECTED"
    assert rule.next_task == "NONE"
    assert rule.mark_status == Status.REJECTED

# --- Interview Scenarios ---

def test_evaluate_transition_interview_passed(interview_task_blueprint: TaskBlueprint) -> None:
    """
    Validates that specific string matching works for the interview payload.
    """
    payload: Dict[str, Any] = {"decision": "passed_interview"}
    
    rule = evaluate_transition(task_blueprint=interview_task_blueprint, payload=payload)
    
    assert rule.next_step == "sign_contract"
    assert rule.next_task == "upload_identification_document"

def test_evaluate_transition_interview_failed(interview_task_blueprint: TaskBlueprint) -> None:
    """
    Validates that any unexpected string in the interview payload results in rejection.
    """
    payload: Dict[str, Any] = {"decision": "failed_interview"}
    
    rule = evaluate_transition(task_blueprint=interview_task_blueprint, payload=payload)
    
    assert rule.next_step == "TERMINAL_REJECTED"
    assert rule.mark_status == Status.REJECTED

# --- AUTO_PASS Scenarios ---

def test_evaluate_transition_auto_pass(auto_pass_task_blueprint: TaskBlueprint) -> None:
    """
    Validates that AUTO_PASS tasks immediately return the DEFAULT transition, 
    ignoring the payload entirely.
    """
    # Even if payload is empty or None, AUTO_PASS must succeed
    payload: Dict[str, Any] = {}
    
    rule = evaluate_transition(task_blueprint=auto_pass_task_blueprint, payload=payload)
    
    assert rule.next_step == "iq_test"
    assert rule.next_task == "perform_iq_test"