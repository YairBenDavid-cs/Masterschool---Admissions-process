"""
Masterschool Admissions — Candidate Portal
A Streamlit-powered onboarding wizard backed by the FastAPI admissions engine.

Usage:
    streamlit run candidate_portal.py

Requirements:
    pip install streamlit httpx
    FastAPI server running at http://localhost:8000
"""

from typing import Optional

import httpx
import streamlit as st

# =============================================================================
# CONFIGURATION
# =============================================================================

API_BASE = "http://localhost:8000"

STEP_DISPLAY_NAMES: dict[str, str] = {
    "personal_details": "Personal Details",
    "iq_test":          "IQ Test",
    "interview":        "Interview",
    "sign_contract":    "Sign Contract",
    "payment":          "Payment",
    "join_slack":       "Join Slack",
}

TASK_LABELS: dict[str, tuple[str, str]] = {
    "submit_personal_details":        ("📋", "Submit Personal Details"),
    "schedule_interview":             ("📅", "Schedule Interview"),
    "upload_identification_document": ("📄", "Upload ID Document"),
    "sign_contract_task":             ("✍️",  "Sign Contract"),
    "process_payment":                ("💳", "Process Payment"),
    "join_slack_task":                ("💬", "Join Slack Workspace"),
    "second_chance_iq":               ("🧠", "Second-Chance IQ Assessment"),
    "iq_test_task":                   ("🧠", "IQ Assessment"),
}

IQ_TIERS = [
    ("Genius",        95),
    ("Above Average", 80),
    ("Average",       67),
    ("Below Average", 40),
]


# =============================================================================
# HTTP HELPERS
# =============================================================================

@st.cache_resource
def get_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE, timeout=10.0)


def post_register(email: str) -> httpx.Response:
    return get_client().post("/api/v1/users", json={"email": email})


def put_complete_task(
    user_id: str,
    current_step: str,
    current_task: str,
    task_payload: dict,
) -> httpx.Response:
    return get_client().put("/api/v1/tasks/complete", json={
        "user_id":      user_id,
        "current_step": current_step,
        "current_task": current_task,
        "task_payload": task_payload,
    })


def get_user_flow(user_id: str) -> httpx.Response:
    return get_client().get(f"/api/v1/users/{user_id}/flow")


# =============================================================================
# TASK WIDGET
# =============================================================================

def render_task_widget(current_task: str, schema: list) -> Optional[dict]:
    """
    Render a task-specific UI widget and return the payload dict when the
    user submits. Returns None if the user hasn't acted yet.
    """

    # --- Specific task: IQ Test ---
    if current_task == "perform_iq_test":
        st.markdown("#### IQ Assessment")
        st.markdown("Select the range that best describes your result:")
        labels  = [f"{name} (score: {val})" for name, val in IQ_TIERS]
        choice  = st.selectbox("Score range", labels, label_visibility="collapsed")
        tier_name = choice.split(" (")[0]
        score   = dict(IQ_TIERS)[tier_name]
        if st.button("Submit IQ Test", use_container_width=True, type="primary"):
            return {"score": score}
        return None

    # --- Specific task: Second-chance IQ ---
    if current_task == "second_chance_iq":
        st.markdown("#### Second-Chance IQ Assessment")
        st.info("You qualify for a second attempt. Make it count!")
        labels  = [f"{name} (score: {val})" for name, val in IQ_TIERS]
        choice  = st.selectbox("Score range", labels, label_visibility="collapsed")
        tier_name = choice.split(" (")[0]
        score   = dict(IQ_TIERS)[tier_name]
        if st.button("Submit Second Attempt", use_container_width=True, type="primary"):
            return {"score": score}
        return None

    # --- Specific task: Interview ---
    if current_task == "perform_interview":
        st.markdown("#### Interview Outcome")
        st.markdown("Record the interviewer's final decision:")
        decision_label = st.radio(
            "Decision",
            ["Pass ✓", "Fail ✗"],
            label_visibility="collapsed",
            horizontal=True,
        )
        decision = "pass" if "Pass" in decision_label else "fail"
        if st.button("Record Outcome", use_container_width=True, type="primary"):
            return {"decision": decision}
        return None

    # --- AUTO-PASS tasks (empty schema) ---
    if not schema:
        icon, label = TASK_LABELS.get(current_task, ("▶️", current_task.replace("_", " ").title()))
        st.info(f"{icon}  Ready to proceed: **{label}**")
        if st.button("Continue →", use_container_width=True, type="primary"):
            return {}
        return None

    # --- Generic fallback: schema-driven inputs ---
    st.markdown("#### Complete This Task")
    form_values: dict = {}
    for field in schema:
        key   = field["key_name"]
        vtype = field.get("value_type", "str")
        desc  = field.get("description", key)
        ex    = field.get("example")
        av    = field.get("allowed_values")

        if vtype == "int":
            form_values[key] = st.number_input(desc, value=int(ex) if ex is not None else 0, step=1)
        elif vtype == "float":
            form_values[key] = st.number_input(desc, value=float(ex) if ex is not None else 0.0)
        elif vtype == "bool":
            form_values[key] = st.checkbox(desc, value=bool(ex) if ex is not None else False)
        elif av:
            form_values[key] = st.selectbox(desc, av, index=av.index(ex) if ex in av else 0)
        else:
            form_values[key] = st.text_input(desc, value=str(ex) if ex is not None else "")

    if st.button("Submit", use_container_width=True, type="primary"):
        return form_values
    return None


# =============================================================================
# PAGES
# =============================================================================

def welcome_page() -> None:
    st.markdown(
        "<h1 style='text-align:center'>🎓 Masterschool Admissions</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center; color:gray'>Your journey to a new career starts here.</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        email = st.text_input("Email address", placeholder="candidate@example.com")
        if st.button("Start Journey →", use_container_width=True, type="primary"):
            if not email.strip():
                st.error("Please enter your email address.")
                return
            with st.spinner("Registering..."):
                resp = post_register(email.strip())
            if resp.status_code == 201:
                data = resp.json()
                st.session_state.user_id   = data["user_id"]
                st.session_state.user_data = data
                st.rerun()
            elif resp.status_code == 400:
                st.error("This email is already registered. Please use a different address.")
            elif resp.status_code == 422:
                st.error("Please enter a valid email address.")
            else:
                st.error(f"Unexpected error ({resp.status_code}). Is the server running?")


def flow_page() -> None:
    user_id   = st.session_state.user_id
    user_data = st.session_state.user_data

    current_step = user_data.get("current_step", "")
    current_task = user_data.get("current_task", "")
    schema       = user_data.get("current_task_schema", [])
    progress     = user_data.get("progress", {})

    # --- Sidebar ---
    with st.sidebar:
        st.markdown("### Your Session")
        st.code(user_id, language=None)
        st.caption("Share this ID to resume your application.")
        st.divider()
        if st.button("🔄 Reset Session", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    # --- Header + Progress Bar ---
    st.markdown("## Masterschool Admissions Portal")

    idx   = progress.get("current_step_index", 0)
    total = progress.get("total_steps", 1)
    ratio = idx / total if total else 0.0

    step_display = STEP_DISPLAY_NAMES.get(current_step, current_step.replace("_", " ").title())
    st.progress(ratio)
    st.caption(f"Step {idx} of {total}  ·  **{step_display}**")
    st.divider()

    # --- Task Card ---
    st.markdown(f"### {step_display}")

    # --- Dynamic Task Widget ---
    payload = render_task_widget(current_task, schema)

    if payload is not None:
        with st.spinner("Processing..."):
            resp = put_complete_task(user_id, current_step, current_task, payload)

        if resp.status_code == 200:
            st.session_state.user_data = resp.json()
            st.rerun()
        elif resp.status_code == 422:
            detail = resp.json().get("detail", "Validation error.")
            st.error(f"Validation error: {detail}")
        elif resp.status_code == 400:
            detail = resp.json().get("detail", "Request error.")
            st.error(f"Error: {detail}")
        else:
            st.error(f"Unexpected server error ({resp.status_code}).")


def outcome_page() -> None:
    user_id   = st.session_state.user_id
    user_data = st.session_state.user_data
    status    = user_data.get("status")

    with st.sidebar:
        st.markdown("### Your Session")
        st.code(user_id, language=None)
        st.divider()
        if st.button("🔄 Start Over", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    if status == "ACCEPTED":
        st.balloons()
        st.markdown(
            "<h1 style='text-align:center'>🎉 Congratulations!</h1>",
            unsafe_allow_html=True,
        )
        st.success(
            "You've been **accepted** to Masterschool! "
            "Welcome to the community. Check your email for next steps."
        )
        st.markdown("---")
        st.markdown(
            "<p style='text-align:center'>We can't wait to see what you'll build.</p>",
            unsafe_allow_html=True,
        )

    elif status == "REJECTED":
        # Fetch outcome from the flow endpoint (it lives in UserFlowResponse, not UserStatusResponse)
        outcome: dict = {}
        flow_resp = get_user_flow(user_id)
        if flow_resp.status_code == 200:
            outcome = flow_resp.json().get("outcome") or {}

        failed_task = outcome.get("failed_at_task", "unknown")

        task_entry = TASK_LABELS.get(failed_task)
        task_label = task_entry[1] if task_entry else failed_task.replace("_", " ").title()

        st.markdown(
            "<h1 style='text-align:center'>Application Update</h1>",
            unsafe_allow_html=True,
        )
        st.error("Unfortunately, your application was not successful.")
        st.markdown(
            f"After careful review, we were unable to move your application forward "
            f"at the **{task_label}** stage."
        )
        st.divider()
        st.markdown("We appreciate your interest in Masterschool and encourage you to apply again in the future.")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    st.set_page_config(
        page_title="Masterschool Admissions",
        page_icon="🎓",
        layout="centered",
    )

    # Initialize session state
    if "user_id"   not in st.session_state:
        st.session_state.user_id   = None
    if "user_data" not in st.session_state:
        st.session_state.user_data = None

    user_id   = st.session_state.user_id
    user_data = st.session_state.user_data
    status    = user_data.get("status") if user_data else None

    if not user_id:
        welcome_page()
    elif status in ("ACCEPTED", "REJECTED"):
        outcome_page()
    else:
        flow_page()


if __name__ == "__main__":
    main()
