#!/usr/bin/env python3
"""
API Explorer — Interactive HATEOAS-Driven Sandbox for the Admissions Engine.

Allows manual testing of all 6 endpoints with:
  - Contextual menu highlighting based on the last server response
  - HATEOAS link discovery banners
  - JIT schema hints and example pre-fill for PUT /tasks/complete
  - Full colorized JSON output

Usage:
    python scripts/api_explorer.py

Requirements:
    Server must be running at http://localhost:8000
"""

import json
import os
import sys
from typing import Optional

import httpx
import questionary

BASE_URL  = os.environ.get("API_URL", "http://localhost:8000")
SEPARATOR = "=" * 66

# ANSI colors
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

_STATUS_TEXT = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    404: "Not Found",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def print_request(method: str, url: str, payload: Optional[dict] = None) -> None:
    print(f"\n  {_BOLD}► {method}  {url}{_RESET}")
    if payload is not None:
        print(f"  Payload: {json.dumps(payload)}")


def print_response(resp: httpx.Response) -> None:
    code        = resp.status_code
    status_txt  = _STATUS_TEXT.get(code, str(code))
    is_error    = code >= 400
    color       = _RED if is_error else _CYAN

    print(f"\n{color}  ◄ {code} {status_txt}{_RESET}")
    try:
        body = resp.json()
        print(f"{color}{json.dumps(body, indent=4)}{_RESET}")
    except Exception:
        print(f"{color}  {resp.text}{_RESET}")


def print_hateoas_discovery(resp_json: dict) -> None:
    """Print HATEOAS link + JIT schema discovery banners in yellow."""
    links  = resp_json.get("_links", {})
    schema = resp_json.get("current_task_schema", [])

    next_action = links.get("next_action")
    if next_action:
        method = next_action.get("method", "?")
        href   = next_action.get("href", "?")
        desc   = next_action.get("description", "")
        print(f"\n  {_YELLOW}{_BOLD}[!] HATEOAS: Next action discovered via API links.{_RESET}")
        print(f"  {_YELLOW}    → next_action: {method} {href}  (\"{desc}\"){_RESET}")

    if schema:
        task_name = resp_json.get("task_name", "?")
        print(f"\n  {_YELLOW}{_BOLD}[!] JIT Schema: Task schema discovered for '{task_name}'.{_RESET}")
        for field in schema:
            key   = field.get("key_name", "?")
            vtype = field.get("value_type", "?")
            desc  = field.get("description", "")
            ex    = field.get("example")
            av    = field.get("allowed_values")

            line = f"      {key}  [{vtype}]  {desc}"
            if av:
                line += f"  allowed: {av}"
            if ex is not None:
                line += f"  (e.g. {ex})"
            print(f"  {_YELLOW}{line}{_RESET}")


def _suggest(current_user_id: Optional[str], last_response: Optional[dict]) -> str:
    """Derive which menu option to highlight based on session state."""
    if current_user_id is None:
        return "1"
    if last_response is None:
        return "4"
    if last_response.get("_links", {}).get("next_action"):
        return "5"
    if last_response.get("progress", {}).get("is_terminal"):
        return "3"
    return "4"


def build_menu_choices(
    current_user_id: Optional[str],
    last_response: Optional[dict],
) -> tuple[list, str]:
    """Build questionary Choice objects for the arrow-key select menu."""
    suggested = _suggest(current_user_id, last_response)

    rows = [
        ("1", "POST", "/api/v1/users",              "Register a New Candidate"),
        ("2", "GET",  "/api/v1/flow",               "Full FSM Flow Blueprint"),
        ("3", "GET",  "/api/v1/users/{id}/flow",    "Candidate's Personalized Flow"),
        ("4", "GET",  "/api/v1/users/{id}/current", "Current Step & Task"),
        ("5", "PUT",  "/api/v1/tasks/complete",     "Complete a Task & Advance the FSM"),
        ("6", "GET",  "/api/v1/users/{id}/status",  "Admission Status"),
        ("0", "",     "",                           "Exit"),
    ]

    choices = []
    for num, method, path, label in rows:
        arrow = " →" if num == suggested else "   "
        title = f"[{num}]{arrow}  {method:<5}  {path:<40}  {label}"
        choices.append(questionary.Choice(title=title, value=num))
    return choices, suggested


# =============================================================================
# USER ID RESOLUTION
# =============================================================================

def resolve_user_id(stored_id: Optional[str]) -> Optional[str]:
    """Return the stored user_id silently, or prompt once if none is stored."""
    if stored_id:
        return stored_id
    raw = input("  Enter user_id: ").strip()
    if not raw:
        print("  ✗  user_id is required.")
        return None
    return raw


# =============================================================================
# ACTIONS
# =============================================================================

def action_register(client: httpx.Client) -> Optional[str]:
    """POST /api/v1/users — prompts for email, returns user_id on success."""
    email = input("  Enter candidate email: ").strip()
    if not email:
        print("  ✗  Email cannot be empty.")
        return None

    url = "/api/v1/users"
    payload = {"email": email}
    print_request("POST", BASE_URL + url, payload)
    resp = client.post(url, json=payload)
    print_response(resp)

    if resp.status_code == 201:
        resp_json = resp.json()
        print_hateoas_discovery(resp_json)
        user_id = resp_json.get("user_id")
        print(f"\n  ✓  Registered! user_id stored: {user_id}")
        return resp_json
    return None


def action_get_flow(client: httpx.Client) -> None:
    """GET /api/v1/flow — no user_id required."""
    url = "/api/v1/flow"
    print_request("GET", BASE_URL + url)
    resp = client.get(url)
    print_response(resp)


def action_get_user_flow(client: httpx.Client, stored_id: Optional[str]) -> None:
    """GET /api/v1/users/{id}/flow"""
    user_id = resolve_user_id(stored_id)
    if not user_id:
        return
    url = f"/api/v1/users/{user_id}/flow"
    print_request("GET", BASE_URL + url)
    resp = client.get(url)
    print_response(resp)


def action_get_current(client: httpx.Client, stored_id: Optional[str]) -> None:
    """GET /api/v1/users/{id}/current"""
    user_id = resolve_user_id(stored_id)
    if not user_id:
        return
    url = f"/api/v1/users/{user_id}/current"
    print_request("GET", BASE_URL + url)
    resp = client.get(url)
    print_response(resp)


def action_complete_task(
    client: httpx.Client,
    stored_id: Optional[str],
    last_response: Optional[dict],
) -> Optional[dict]:
    """PUT /api/v1/tasks/complete — Smart HATEOAS-driven flow."""

    # 1. Resolve user_id
    user_id = resolve_user_id(stored_id)
    if not user_id:
        return None

    # 2. Suggest HATEOAS href if available
    hateoas_href = None
    if last_response:
        next_action = last_response.get("_links", {}).get("next_action", {})
        hateoas_href = next_action.get("href")
        if hateoas_href:
            print(f"\n  {_YELLOW}[!] HATEOAS href from last response: {hateoas_href}{_RESET}")

    # 3. Fetch current step/task silently
    current_resp = client.get(f"/api/v1/users/{user_id}/current")
    if current_resp.status_code != 200:
        print(f"\n  {_RED}✗  Could not fetch current task ({current_resp.status_code}). "
              f"Check the user_id.{_RESET}")
        return None

    current_data  = current_resp.json()
    step_name  = current_data.get("step_name", "")
    task_name  = current_data.get("task_name", "")
    print(f"\n  Current step: {_BOLD}{step_name}{_RESET}  │  "
          f"Current task: {_BOLD}{task_name}{_RESET}")

    # 4. Show JIT schema hints from last_response
    schema = (last_response or {}).get("current_task_schema", [])
    if not schema:
        print(f"\n  {_YELLOW}  AUTO-PASS — no payload fields required.{_RESET}")
    else:
        print(f"\n  {_YELLOW}Task schema for '{task_name}':{_RESET}")
        for field in schema:
            key   = field.get("key_name", "?")
            vtype = field.get("value_type", "?")
            desc  = field.get("description", "")
            ex    = field.get("example")
            av    = field.get("allowed_values")
            line  = f"    {key}  [{vtype}]  {desc}"
            if av:
                line += f"  {_BOLD}allowed: {av}{_RESET}{_YELLOW}"
            if ex is not None:
                line += f"  (e.g. {ex})"
            print(f"  {_YELLOW}{line}{_RESET}")

    # 5. Example pre-fill offer
    task_payload: dict = {}
    has_examples = schema and all(f.get("example") is not None for f in schema)

    if has_examples:
        example_payload = {f["key_name"]: f["example"] for f in schema}
        print(f"\n  Example payload: {_CYAN}{json.dumps(example_payload)}{_RESET}")
        choice = input("\n  Would you like to use example values? (y/n): ").strip().lower()
        if choice == "y":
            task_payload = example_payload
            print(f"  Pre-filled payload: {_CYAN}{json.dumps(task_payload)}{_RESET}")
        else:
            task_payload = _prompt_json_payload()
    elif schema:
        task_payload = _prompt_json_payload()
    # else AUTO_PASS → task_payload stays {}

    # 6. Allow override of task_name (step_name is used silently)
    print(f"\n  task_name  (Enter for '{task_name}'): ", end="")
    override_task = input().strip()
    if override_task:
        task_name = override_task

    # 7. PUT
    url     = "/api/v1/tasks/complete"
    body    = {
        "user_id":      user_id,
        "step_name":    step_name,
        "task_name":    task_name,
        "task_payload": task_payload,
    }
    print_request("PUT", BASE_URL + url, body)
    resp = client.put(url, json=body)
    print_response(resp)

    if resp.status_code == 200:
        resp_json = resp.json()
        print_hateoas_discovery(resp_json)
        return resp_json
    return None


def _prompt_json_payload() -> dict:
    """Prompt for a raw JSON string, re-prompting on parse errors."""
    while True:
        raw = input("  Enter task_payload JSON (default={}): ").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            print("  ✗  Expected a JSON object (e.g. {\"score\": 85}). Try again.")
        except json.JSONDecodeError as exc:
            print(f"  ✗  Invalid JSON: {exc}. Try again.")


def action_get_status(client: httpx.Client, stored_id: Optional[str]) -> None:
    """GET /api/v1/users/{id}/status"""
    user_id = resolve_user_id(stored_id)
    if not user_id:
        return
    url = f"/api/v1/users/{user_id}/status"
    print_request("GET", BASE_URL + url)
    resp = client.get(url)
    print_response(resp)


# =============================================================================
# MAIN LOOP
# =============================================================================

def run() -> None:
    current_user_id: Optional[str]  = None
    last_response:   Optional[dict] = None

    with httpx.Client(base_url=BASE_URL) as client:
        while True:
            short_id = current_user_id[:8] + "..." if current_user_id else "None"
            print(f"\n  {SEPARATOR}")
            print(f"    {_BOLD}API EXPLORER{_RESET}  │  Stored user_id: {short_id}  │  Server: :8000")
            print(f"  {SEPARATOR}")

            choices, suggested = build_menu_choices(current_user_id, last_response)
            choice = questionary.select(
                "  Select an action:",
                choices=choices,
                default=suggested,
            ).ask()

            if choice is None or choice == "0":
                print("\n  Goodbye.\n")
                break

            elif choice == "1":
                result = action_register(client)
                if result:
                    current_user_id = result.get("user_id")
                    last_response   = result

            elif choice == "2":
                action_get_flow(client)

            elif choice == "3":
                action_get_user_flow(client, current_user_id)

            elif choice == "4":
                action_get_current(client, current_user_id)

            elif choice == "5":
                result = action_complete_task(client, current_user_id, last_response)
                if result:
                    last_response = result

            elif choice == "6":
                action_get_status(client, current_user_id)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Goodbye.\n")
        sys.exit(0)
    except httpx.ConnectError:
        print(f"\n  ✗  Cannot connect to {BASE_URL}.")
        print("     Make sure the server is running:")
        print("     .venv/bin/uvicorn app.main:app --reload\n")
        sys.exit(1)
