#!/usr/bin/env python3
"""
Interactive E2E demo client for the Masterschool Admissions Engine.

Walks a user through the entire FSM flow by following the API's own
HATEOAS links and JIT task schemas — never hardcoding task names or fields.

Usage:
    python run_interactive_demo.py

Requirements:
    Server must be running at http://localhost:8000
    httpx must be installed (included in requirements.txt)
"""

import sys
import httpx

BASE_URL = "http://localhost:8000"
SEPARATOR = "=" * 62

# Maps the value_type strings from the API schema to Python callables.
TYPE_CASTERS = {
    "int": int,
    "str": str,
    "float": float,
    "bool": lambda v: v.strip().lower() in ("true", "1", "yes"),
}


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def print_banner() -> None:
    print(f"\n{SEPARATOR}")
    print("  MASTERSCHOOL ADMISSIONS ENGINE — Interactive Demo")
    print("  Driven entirely by HATEOAS links and JIT task schemas.")
    print(SEPARATOR)


def print_state(user_data: dict) -> None:
    """Render the user's current FSM position to the console."""
    progress = user_data.get("progress", {})
    status = user_data.get("status", "—")
    ratio = progress.get("completion_ratio", "—")
    step = user_data.get("current_step") or "—"
    task = user_data.get("current_task") or "—"

    print(f"\n{SEPARATOR}")
    print(f"  Status  :  {status}")
    print(f"  Progress:  {ratio}")
    print(f"  Step    :  {step}")
    print(f"  Task    :  {task}")
    print(SEPARATOR)


def print_error(status_code: int, detail) -> None:
    """Pretty-print a 400 or 422 error response."""
    print(f"\n  ✗  Validation error ({status_code}):")
    if isinstance(detail, list):
        for err in detail:
            loc = err.get("loc", [])
            msg = err.get("msg", "")
            print(f"       • {loc} — {msg}")
    else:
        print(f"       {detail}")


# =============================================================================
# PAYLOAD BUILDER
# =============================================================================

def prompt_payload(schema: list) -> dict:
    """
    Dynamically prompt for each field declared in current_task_schema.

    Re-prompts on type-cast failure so the script never crashes on bad input.
    Returns a fully typed payload dict ready for submission.
    """
    payload: dict = {}
    print("\n  This task requires input:\n")

    for field in schema:
        key = field["key_name"]
        vtype = field["value_type"]
        description = field.get("description", "")
        example = field.get("example")

        # Build the prompt line
        hint_parts = [f"[{vtype}]"]
        if description:
            hint_parts.append(description)
        if example is not None:
            hint_parts.append(f"(e.g. {example})")
        hint = " ".join(hint_parts)

        caster = TYPE_CASTERS.get(vtype, str)

        while True:
            raw = input(f"  {key} {hint}: ").strip()
            try:
                payload[key] = caster(raw)
                break
            except (ValueError, TypeError):
                print(f"  ✗  Expected {vtype}, got '{raw}'. Try again.")

    return payload


# =============================================================================
# MAIN FLOW
# =============================================================================

def run() -> None:
    print_banner()

    # -------------------------------------------------------------------------
    # Step 1 — Register the candidate (retry loop for 400/422)
    # -------------------------------------------------------------------------
    with httpx.Client(base_url=BASE_URL) as client:
        while True:
            email = input("\n  Enter candidate email: ").strip()
            if not email:
                print("  ✗  Email cannot be empty. Try again.")
                continue

            resp = client.post("/api/v1/users", json={"email": email})

            if resp.status_code == 201:
                user_data = resp.json()
                user_id = user_data["user_id"]
                print(f"\n  ✓  Registered! user_id: {user_id}")
                break

            if resp.status_code in (400, 422):
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                print_error(resp.status_code, detail)
                print("\n  Please try a different email.\n")
                continue

            # Unexpected error — not recoverable
            print(f"\n  ✗  Unexpected error ({resp.status_code}): {resp.text}")
            sys.exit(1)

    # -------------------------------------------------------------------------
    # Step 2 — Drive the flow using HATEOAS links and JIT schemas
    # -------------------------------------------------------------------------
    with httpx.Client(base_url=BASE_URL) as client:
        while True:
            print_state(user_data)

            # Terminal check
            progress = user_data.get("progress", {})
            if progress.get("is_terminal"):
                final_status = user_data.get("status", "UNKNOWN")
                print(f"\n{SEPARATOR}")
                print(f"  ★  FINAL STATUS: {final_status}")
                print(SEPARATOR + "\n")
                break

            # Extract the HATEOAS next action link
            links = user_data.get("_links", {})
            next_action = links.get("next_action", {})
            href = next_action.get("href")

            if not href:
                print("\n  ✗  No next_action link in response. Cannot continue.")
                sys.exit(1)

            current_step = user_data.get("current_step", "")
            current_task = user_data.get("current_task", "")
            schema = user_data.get("current_task_schema", [])

            # Build the payload — empty for AUTO_PASS, prompted for EVALUATE_PAYLOAD
            if not schema:
                print(f"\n  → AUTO-PASS task '{current_task}'. Submitting empty payload...")
                payload: dict = {}
            else:
                payload = prompt_payload(schema)

            # Submit via the HATEOAS-provided URL
            put_resp = client.put(
                href,
                json={
                    "user_id": user_id,
                    "current_step": current_step,
                    "current_task": current_task,
                    "task_payload": payload,
                },
            )

            # Graceful handling of 400/422 — loop continues so user can retry
            if put_resp.status_code in (400, 422):
                try:
                    detail = put_resp.json().get("detail", put_resp.text)
                except Exception:
                    detail = put_resp.text
                print_error(put_resp.status_code, detail)
                print("\n  Retrying task — please re-enter the values.\n")
                continue

            # Any other non-200 is unexpected
            if put_resp.status_code != 200:
                print(f"\n  ✗  Unexpected error ({put_resp.status_code}): {put_resp.text}")
                sys.exit(1)

            # Advance to next state using the response as the new source of truth
            user_data = put_resp.json()
            print(f"\n  ✓  Task '{current_task}' completed.")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n  Demo interrupted. Goodbye.\n")
        sys.exit(0)
    except httpx.ConnectError:
        print(f"\n  ✗  Cannot connect to {BASE_URL}.")
        print("     Make sure the server is running:")
        print("     .venv/bin/uvicorn app.main:app --reload\n")
        sys.exit(1)
