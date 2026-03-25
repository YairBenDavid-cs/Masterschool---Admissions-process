"""
OpenAPI response documentation for the Admissions Engine API.

Each constant maps directly to one specific exception scenario in routes.py.
Storing them here keeps routes.py focused on routing logic and prevents
reuse of generic error descriptions across routes with different failure modes.
"""

# ---------------------------------------------------------------------------
# POST /api/v1/users
# ---------------------------------------------------------------------------

POST_USERS_400 = {
    "description": "Email already registered",
    "content": {"application/json": {"example": {
        "detail": "Email 'candidate@masterschool.com' is already registered."
    }}}
}

POST_USERS_422 = {
    "description": "Unprocessable Entity — email field missing or not a valid email address",
    "content": {
        "application/json": {
            "examples": {
                "missing_email": {
                    "summary": "email field not provided",
                    "value": {
                        "detail": [
                            {
                            "type": "missing",
                            "loc": [
                                "body",
                                "email"
                            ],
                            "msg": "Field required",
                            "input": {},
                            "url": "https://errors.pydantic.dev/2.6/v/missing"
                            }
                        ]
                    }
                },
                "invalid_email": {
                    "summary": "value is not a valid email address",
                    "value": {
                        "detail": [
                            {
                            "type": "value_error",
                            "loc": [
                                "body",
                                "email"
                            ],
                            "msg": "value is not a valid email address: An email address must have an @-sign.",
                            "input": "candidatemasterschool.com",
                            "ctx": {
                                "reason": "An email address must have an @-sign."
                            }
                            }
                        ]
                    }
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# PUT /api/v1/tasks/complete
# ---------------------------------------------------------------------------

PUT_TASKS_COMPLETE_400 = {
    "description": "Bad Request — workflow state violation or task/step mismatch",
    "content": {
        "application/json": {
            "examples": {
                "terminal_state": {
                    "summary": "User already in terminal state",
                    "value": {"detail": "User abc-123 is already in a terminal state: REJECTED"}
                },
                "task_mismatch": {
                    "summary": "Submitted task does not match user's current task",
                    "value": {
                        "detail": "Task mismatch: user is on 'perform_iq_test', "
                                  "but 'schedule_interview' was submitted."
                    }
                }
            }
        }
    }
}

PUT_TASKS_COMPLETE_404 = {
    "description": "User not found",
    "content": {"application/json": {"example": {
        "detail": "User with ID 'abc-123' not found."
    }}}
}

PUT_TASKS_COMPLETE_422 = {
    "description": "Unprocessable Entity — payload contract violation (missing or wrong-type field)",
    "content": {
        "application/json": {
            "examples": {
                "missing_field": {
                    "summary": "Required field missing",
                    "value": {
                        "detail": "Task 'perform_iq_test' requires field 'score' "
                                  "(type: int) but it was not provided."
                    }
                },
                "wrong_type": {
                    "summary": "Wrong field type",
                    "value": {
                        "detail": "Task 'perform_iq_test': field 'score' must be 'int', got 'str'."
                    }
                },
                "allowed_values_violation": {
                    "summary": "Value not in allowed list",
                    "value": {
                        "detail": "Task 'perform_interview': field 'decision' must be one of ['pass', 'fail'], got 'passed_interview'."
                    }
                },
                "invalid_uuid_body": {
                    "summary": "user_id is not a valid UUID",
                    "value": {
                        "detail": [
                            {
                                "type": "uuid_parsing",
                                "loc": ["body", "user_id"],
                                "msg": "Input should be a valid UUID",
                                "input": "not-a-uuid"
                            }
                        ]
                    }
                }
            }
        }
    }
}

PUT_TASKS_COMPLETE_500 = {
    "description": "Internal Server Error — FSM rule evaluation failure or missing task configuration",
    "content": {"application/json": {"example": {
        "detail": "Internal server error during rule evaluation. Please contact system administrator."
    }}}
}

# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}/* — 422 for malformed UUID path parameter
# ---------------------------------------------------------------------------

DEFAULT_VALIDATION_422 = {
    "description": "Unprocessable Entity — user_id is not a valid UUID",
    "content": {
        "application/json": {
            "examples": {
                "invalid_uuid": {
                    "summary": "Malformed UUID in path",
                    "value": {
                        "detail": [
                            {
                                "type": "uuid_parsing",
                                "loc": ["path", "user_id"],
                                "msg": "Input should be a valid UUID, invalid character: "
                                       "expected an optional prefix of `urn:uuid:` followed by "
                                       "[0-9a-fA-F-], found `n` at 0",
                                "input": "not-a-valid-uuid"
                            }
                        ]
                    }
                },
                "missing_user_id": {
                    "summary": "Missing user_id field in request body",
                    "value": {
                        "detail": [
                            {
                                "type": "missing",
                                "loc": ["body", "user_id"],
                                "msg": "Field required",
                                "input": {}
                            }
                        ]
                    }
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}/* — shared 404 for all user-lookup endpoints
# ---------------------------------------------------------------------------

USER_LOOKUP_404 = {
    "description": "User not found",
    "content": {"application/json": {"example": {
        "detail": "User with ID 'abc-123' not found."
    }}}
}
