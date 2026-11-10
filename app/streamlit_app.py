"""Chat UI for the Maritime Hypercare Agents.

Runs both as a Streamlit-in-Snowflake app and locally:
    streamlit run app/streamlit_app.py
"""
import importlib
import json
import os
import re

import streamlit as st

import hypercare_agents

st.set_page_config(page_title="Maritime Hypercare Agents", page_icon="🚢", layout="wide")

CITATION_CSS = """
<style>
.cite-chip {
    display: inline-flex;
    align-items: center;
    background: #f0f0f0;
    color: #555;
    font-size: 0.75em;
    font-weight: 500;
    padding: 1px 7px;
    border-radius: 10px;
    margin: 0 1px;
    vertical-align: middle;
    line-height: 1.6;
    white-space: nowrap;
}
.cite-chip.doc { background: #e8f0fe; color: #1a56db; }
.cite-chip.data { background: #e6f4ea; color: #137333; }
</style>
"""


def _truncate(name: str, maxlen: int = 25) -> str:
    name = name.strip()
    return name if len(name) <= maxlen else name[:maxlen - 1] + "\u2026"


def render_citations(text: str) -> str:
    """Replace [DOC-XXX: file] and [DATA: TABLE] with styled chips."""
    def _doc_chip(m):
        num, filename = m.group(1), m.group(2)
        short = _truncate(filename)
        safe_full = filename.replace('"', '&quot;')
        return f'<span class="cite-chip doc" title="{safe_full}">DOC-{num}: {short}</span>'

    text = re.sub(r'\[DOC-(\d+):\s*([^\]]+)\]', _doc_chip, text)
    text = re.sub(
        r'\[DATA:\s*([^\]]+)\]',
        r'<span class="cite-chip data" title="\1">DATA: \1</span>',
        text,
    )
    # Also catch bare citations in the Sources line (no brackets):
    # "DOC-001: filename.pdf" and "DATA: BOOKINGS"
    def _bare_doc_chip(m):
        num, filename = m.group(1), m.group(2)
        # Skip if already inside a span (already rendered)
        if 'cite-chip' in text[max(0, m.start()-30):m.start()]:
            return m.group(0)
        short = _truncate(filename)
        safe_full = filename.replace('"', '&quot;')
        return f'<span class="cite-chip doc" title="{safe_full}">DOC-{num}: {short}</span>'

    text = re.sub(r'(?<!\>)DOC-(\d+):\s*([^,\n<]+)', _bare_doc_chip, text)
    text = re.sub(r'(?<!\>)DATA:\s*([A-Z_]+)', r'<span class="cite-chip data" title="\1">DATA: \1</span>', text)
    return text


def render_kb_healing(proposal_json: str):
    """Show KB healing proposal as an expandable info section."""
    if not proposal_json:
        return
    try:
        proposal = json.loads(proposal_json)
    except (json.JSONDecodeError, TypeError):
        return
    if not proposal.get("gap_detected"):
        return
    with st.expander("KB Gap Detected — Proposed Update (pending human validation)", expanded=False):
        st.info(f"**Gap:** {proposal.get('description', 'No description')}")
        if proposal.get("target_section"):
            st.markdown(f"**Target section:** `{proposal['target_section']}`")
        if proposal.get("suggested_update"):
            st.markdown("**Suggested update:**")
            st.code(proposal["suggested_update"], language="text")
        if proposal.get("affected_tickets"):
            st.caption(f"Affected tickets: {', '.join(str(t) for t in proposal['affected_tickets'])}")

importlib.reload(hypercare_agents)

# Inside Snowflake, reuse the app's Snowpark connection. Locally, the agents
# module builds its own session from environment variables (.env).
if hypercare_agents.running_in_snowflake():
    conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
    hypercare_agents.set_session(conn.session())


def load_graph():
    return hypercare_agents.build_graph()


def run_agent(prompt: str):
    with st.chat_message("assistant"):
        with st.spinner("Agents working..."):
            try:
                graph = load_graph()
                result = hypercare_agents.process_ticket(
                    graph,
                    subject=prompt[:120],
                    body=prompt,
                )
                answer = result.get("answer", "I wasn't able to produce an answer for that.")
                trace_text = hypercare_agents.format_trace(result)
                kb_proposal = result.get("kb_healing_proposal", "")

                if result.get("escalated"):
                    st.warning("This has been flagged for escalation to the Pricing Team.")
                    if result.get("escalation_reason"):
                        st.caption(f"Reason: {result['escalation_reason']}")

                st.markdown(CITATION_CSS + render_citations(answer), unsafe_allow_html=True)

                if trace_text:
                    with st.expander("Agent Trace"):
                        st.code(trace_text, language="text")

                render_kb_healing(kb_proposal)

                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": answer,
                    "trace": trace_text,
                    "kb_proposal": kb_proposal,
                })
            except Exception as e:
                error_msg = f"Agent error: {e}"
                st.error(error_msg)
                st.session_state.chat_history.append({"role": "assistant", "content": error_msg})


st.title("Maritime Hypercare Agents")
st.caption("Ask questions about AQUA / SpotOn pricing, routes, bookings, or documentation.")

SUGGESTIONS = {
    "Why is there no offer on route FRLEH to CNSHA?": "Why is there no offer on route FRLEH to CNSHA?",
    "How does SpotOn pricing work?": "How does SpotOn pricing work?",
    "Check booking BK-001 status": "Can you look up booking BK-001 and tell me its current status?",
}

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.markdown(CITATION_CSS + render_citations(msg["content"]), unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])
        if msg.get("trace"):
            with st.expander("Agent Trace"):
                st.code(msg["trace"], language="text")
        if msg.get("kb_proposal"):
            render_kb_healing(msg["kb_proposal"])

prompt = None

if not st.session_state.chat_history:
    selected = st.pills("Try asking:", list(SUGGESTIONS.keys()), label_visibility="collapsed")
    if selected:
        prompt = SUGGESTIONS[selected]

if typed := st.chat_input("Ask the hypercare agents anything..."):
    prompt = typed

if prompt:
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    run_agent(prompt)

