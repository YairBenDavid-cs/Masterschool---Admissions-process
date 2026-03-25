"""
Focused end-to-end flow tests for the Masterschool Admissions Engine.

Test 1 — Happy Path: drives a full ACCEPTED admission from registration to completion.
Test 2 — Second Chance IQ: verifies the FSM dynamically injects second_chance_iq on a
          low IQ score, and that the candidate can still reach ACCEPTED via the second attempt.
"""

import uuid

import pytest
from tests.helpers.utils_api import client, navigate_to_step, navigate_to_task

pytestmark = pytest.mark.E2E
class TestHappyPath:
    def test_full_flow_ends_in_accepted(self):
        """
        Complete end-to-end admission: register → complete every task with
        passing payloads → verify ACCEPTED status via both the task response
        and the dedicated status endpoint.
        """
        # 1. Register a unique candidate
        email = f"happy.{uuid.uuid4().hex[:8]}@test.com"
        resp = client.post("/api/v1/users", json={"email": email})
        assert resp.status_code == 201
        user_data = resp.json()
        user_id = user_data["user_id"]
        assert user_data["status"] == "IN_PROGRESS"

        # 2. Drive the entire flow using spec-compliant default passing payloads.
        #    navigate_to_step stops automatically when status != IN_PROGRESS.
        final = navigate_to_step(user_id, "__terminal__", user_data)

        # 3. Assert the FSM reached the ACCEPTED terminal state
        assert final["status"] == "ACCEPTED"

        # 4. Cross-check via the status endpoint
        status_resp = client.get(f"/api/v1/users/{user_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "ACCEPTED"


class TestSecondChanceIQ:
    def test_low_iq_score_injects_second_chance_task(self):
        """
        Edge case: submitting a score below the passing threshold must cause the
        FSM to dynamically inject the second_chance_iq task into the user's
        custom flow.  Passing the second attempt must still lead to ACCEPTED.
        """
        # 1. Register
        email = f"second_chance.{uuid.uuid4().hex[:8]}@test.com"
        resp = client.post("/api/v1/users", json={"email": email})
        assert resp.status_code == 201
        user_data = resp.json()
        user_id = user_data["user_id"]

        # 2. Advance to the IQ test task
        user_data = navigate_to_task(user_id, "perform_iq_test", user_data)
        assert user_data["task_name"] == "perform_iq_test"

        # 3. Submit a failing IQ score (65 < 76 threshold) — must trigger injection
        resp = client.put("/api/v1/tasks/complete", json={
            "user_id": user_id,
            "step_name": user_data["step_name"],
            "task_name": "perform_iq_test",
            "task_payload": {"score": 65, "test_id": "test-001", "timestamp": 1700000000},
        })
        assert resp.status_code == 200
        user_data = resp.json()

        # 4. Verify the FSM injected second_chance_iq and it is now the active task
        assert "second_chance_iq" in user_data["custom_flow"], (
            "second_chance_iq should be added to custom_flow after a failing IQ score"
        )
        assert user_data["task_name"] == "second_chance_iq"

        # 5. Complete the second chance with a passing score
        resp = client.put("/api/v1/tasks/complete", json={
            "user_id": user_id,
            "step_name": user_data["step_name"],
            "task_name": "second_chance_iq",
            "task_payload": {"score": 85},
        })
        assert resp.status_code == 200
        user_data = resp.json()

        # 6. Drive the remaining tasks to the terminal state
        final = navigate_to_step(user_id, "__terminal__", user_data)
        assert final["status"] == "ACCEPTED"
