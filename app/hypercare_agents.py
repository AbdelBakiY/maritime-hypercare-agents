"""
Maritime Hypercare Agents — multi-agent support system for AQUA / SpotOn
maritime pricing.

Architecture:
  Triage → Knowledge Agent  (FAQ / docs via Cortex Search)
         → Data Agent       (quotes, bookings, price lines via Snowflake SQL)
         → Resolution Agent (synthesises findings, cites sources, or escalates)
         → KB Healing Agent (detects recurring gaps and proposes doc updates)

Uses LangChain + LangGraph with Snowflake Cortex (AI Gateway / REST API).

The module runs in two environments without code changes:
  * inside Snowflake (Streamlit in Snowflake / Snowflake Notebooks): the
    active Snowpark session and the container OAuth token are used;
  * outside Snowflake (local Streamlit, FastAPI, scripts): credentials are
    read from environment variables (see `.env.example`).
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Optional, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

try:  # optional: load a local .env file when running outside Snowflake
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration (environment variables with sensible defaults)
# ---------------------------------------------------------------------------

SNOWFLAKE_TOKEN_PATH = Path("/snowflake/session/token")

DATABASE = os.getenv("HYPERCARE_DATABASE", "HYPERCARE_DB")
SCHEMA = os.getenv("HYPERCARE_SCHEMA", "PUBLIC")
SEARCH_SERVICE = os.getenv("HYPERCARE_SEARCH_SERVICE", "KNOWLEDGE_BASE")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "snowflake").lower()  # snowflake | openai
LLM_MODEL = os.getenv(
    "LLM_MODEL", "openai-gpt-5.4" if LLM_PROVIDER == "snowflake" else "gpt-4o-mini"
)


def fq(name: str) -> str:
    """Fully-qualified object name in the configured database/schema."""
    return f"{DATABASE}.{SCHEMA}.{name}"


def running_in_snowflake() -> bool:
    """True inside a Snowflake container runtime (SiS / Notebooks)."""
    return SNOWFLAKE_TOKEN_PATH.exists()


# ---------------------------------------------------------------------------
# LLM factory — OpenAI-compatible endpoint (Snowflake Cortex or OpenAI)
# ---------------------------------------------------------------------------

def _snowflake_host() -> str:
    host = os.getenv("SNOWFLAKE_HOST")
    if host:
        return host
    account = os.getenv("SNOWFLAKE_ACCOUNT")
    if not account:
        raise RuntimeError("Set SNOWFLAKE_HOST or SNOWFLAKE_ACCOUNT to reach Snowflake Cortex.")
    return f"{account}.snowflakecomputing.com"


def make_llm(model: str | None = None, traceparent: str | None = None) -> ChatOpenAI:
    """Build the chat model.

    * LLM_PROVIDER=snowflake (default): Cortex AI Gateway. Inside Snowflake the
      container session token is used; outside, a Programmatic Access Token
      (SNOWFLAKE_PAT) is required.
    * LLM_PROVIDER=openai: any OpenAI-compatible API (OPENAI_API_KEY, optional
      OPENAI_BASE_URL).
    """
    model = model or LLM_MODEL
    headers: dict[str, str] = {}
    if traceparent:
        headers["traceparent"] = traceparent

    if LLM_PROVIDER == "openai":
        return ChatOpenAI(
            model=model,
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            api_key=os.environ["OPENAI_API_KEY"],
            temperature=0,
            max_tokens=4096,
            default_headers=headers or None,
        )

    if running_in_snowflake():
        token = SNOWFLAKE_TOKEN_PATH.read_text().strip()
    else:
        token = os.getenv("SNOWFLAKE_PAT")
        if not token:
            raise RuntimeError(
                "Outside Snowflake, set SNOWFLAKE_PAT (Programmatic Access Token) "
                "or use LLM_PROVIDER=openai with OPENAI_API_KEY."
            )
    headers["X-Snowflake-Cross-Region"] = "ANY_REGION"
    base_url = os.getenv(
        "LLM_BASE_URL", f"https://{_snowflake_host()}/api/v2/aigateways/SNOWFLAKE/v1"
    )
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=token,
        temperature=0,
        max_tokens=4096,
        default_headers=headers,
    )


# ---------------------------------------------------------------------------
# Snowpark session helper
# ---------------------------------------------------------------------------

_session = None


def set_session(session) -> None:
    """Inject an existing Snowpark session (e.g. from st.connection)."""
    global _session
    _session = session


def _session_from_env():
    """Create a Snowpark session from environment variables or connections.toml."""
    from snowflake.snowpark import Session

    connection_name = os.getenv("SNOWFLAKE_CONNECTION_NAME")
    if connection_name:  # entry in ~/.snowflake/connections.toml
        return Session.builder.config("connection_name", connection_name).create()

    cfg = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        # A Programmatic Access Token can be used in place of a password.
        "password": os.getenv("SNOWFLAKE_PASSWORD") or os.getenv("SNOWFLAKE_PAT"),
        "role": os.getenv("SNOWFLAKE_ROLE"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": DATABASE,
        "schema": SCHEMA,
    }
    if os.getenv("SNOWFLAKE_AUTHENTICATOR"):
        cfg["authenticator"] = os.environ["SNOWFLAKE_AUTHENTICATOR"]
    return Session.builder.configs({k: v for k, v in cfg.items() if v}).create()


def get_session():
    global _session
    if _session is None:
        try:
            from snowflake.snowpark.context import get_active_session

            _session = get_active_session()
        except Exception:
            _session = _session_from_env()
    return _session


def _sql_literal(value: str) -> str:
    """Escape a Python string for use inside a single-quoted Snowflake literal."""
    return value.replace("\\", "\\\\").replace("'", "''")


def run_sql(query: str, params: list | None = None) -> list[dict]:
    """Run a query (with optional qmark `?` bind parameters) and return dict rows."""
    df = get_session().sql(query, params=params) if params else get_session().sql(query)
    col_names = df.columns
    rows = df.collect()
    result = []
    for row in rows:
        d = {}
        for i, col in enumerate(col_names):
            key = col
            if key in d:
                key = f"{key}_{i}"
            d[key] = row[i]
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Triage — structured routing decision
# ---------------------------------------------------------------------------

class TriageDecision(BaseModel):
    reasoning: str = Field(description="Brief chain-of-thought for routing")
    category: Literal[
        "RULE_QUESTION", "PRICE_MISMATCH", "NO_OFFER",
        "BOOKING_ISSUE", "PRICE_LINE_INQUIRY", "ROUTE_INQUIRY",
        "PRICE_LIST_INQUIRY", "TICKET_INQUIRY",
        "FUNCTIONALITY", "RECURRING", "UNKNOWN"
    ] = Field(description="Ticket category")
    route: Literal["knowledge", "data", "both", "clarify", "escalate"] = Field(
        description="knowledge=docs only, data=operational lookup, both=docs+data, clarify=ask user to clarify before proceeding, escalate=contradictory or needs human expert"
    )
    needs_quote: bool = Field(default=False)
    needs_booking: bool = Field(default=False)
    needs_price_line: bool = Field(default=False)
    search_query: Optional[str] = Field(None, description="Query for knowledge base search")
    extracted_quote_id: str = Field(
        default="",
        description="The quote identifier from the ticket. Normalize to QT-XXX (e.g. 'quote 5' -> 'QT-005', 'QT-123' -> 'QT-123', 'quote 009' -> 'QT-009'). Empty string if none mentioned."
    )
    extracted_booking_id: str = Field(
        default="",
        description="The booking identifier from the ticket. Normalize to the format BK-XXX (e.g. 'booking 001' -> 'BK-001', 'BK-004' -> 'BK-004', 'check booking 42' -> 'BK-042'). Empty string if none mentioned."
    )
    extracted_route_id: str = Field(
        default="",
        description="The route identifier from the ticket. Normalize to the format RT-XXX (e.g. 'route 1' -> 'RT-001', 'RT-005' -> 'RT-005'). Empty string if none mentioned."
    )
    extracted_line_id: str = Field(
        default="",
        description="The price line identifier from the ticket. Normalize to LN-XXX (e.g. 'price line 002' -> 'LN-002', 'line 5' -> 'LN-005', 'LN-010' -> 'LN-010'). Empty string if none mentioned."
    )
    extracted_pricelist_id: str = Field(
        default="",
        description="The price list identifier from the ticket. Normalize to PL-XXX (e.g. 'price list 3' -> 'PL-003', 'PL-001' -> 'PL-001'). Empty string if none mentioned."
    )
    extracted_ticket_id: str = Field(
        default="",
        description="The ticket identifier from the ticket. Normalize to TK-XXX (e.g. 'ticket 3' -> 'TK-003', 'TK-010' -> 'TK-010'). Empty string if none mentioned."
    )
    clarification_question: str = Field(
        default="",
        description="When route is 'clarify', a specific question to ask the user to understand their request better. Empty string otherwise."
    )


TRIAGE_SYSTEM = """You are the triage brain of a maritime hypercare support system.
You receive support tickets about AQUA (internal pricing tool) and SpotOn (online sales).

Classify the ticket and decide the routing:
- knowledge: question answerable from documentation/FAQ alone
- data: requires looking up operational data (quotes, bookings, price lines)
- both: needs documentation AND operational data
- clarify: the request is vague or ambiguous — ask the user a specific clarifying question before proceeding
- escalate: contradictory information or confirmed need for human expert (use ONLY after clarification would not help)

Extract whether we need to look up a quote, booking, or price line.
Generate a search_query for the knowledge base if documentation is relevant.

ID EXTRACTION (critical):
Users may refer to IDs in many ways. You MUST extract and normalize them:
- Bookings: "BK-001", "booking 001", "check booking 42", "BKG-004" → extracted_booking_id = "BK-001", "BK-001", "BK-042", "BK-004"
- Quotes: "QT-123", "quote 5", "quote number 12" → extracted_quote_id = "QT-123", "QT-005", "QT-012"
- Routes: "RT-001", "route 3" → extracted_route_id = "RT-001", "RT-003"
- Price lines: "LN-002", "price line 002", "line 5" → extracted_line_id = "LN-002", "LN-002", "LN-005"
- Price lists: "PL-001", "price list 3" → extracted_pricelist_id = "PL-001", "PL-003"
- Tickets: "TK-003", "ticket 3" → extracted_ticket_id = "TK-003", "TK-003"
Always zero-pad to 3 digits. If no ID is mentioned, leave the field as an empty string.

ROUTING RULE: If ANY data ID is mentioned or the user asks about a specific record (booking, quote, route, price line, price list, ticket), ALWAYS route to 'data'. Do NOT route to 'clarify' when the user mentions a specific entity to look up — route to 'data' and let the data agent handle it.

IMPORTANT: Never invent explanations. Prefer 'clarify' over 'escalate' when the user's intent is unclear — only escalate when clarification would not help (e.g. contradictory data, confirmed system issues).

FOLLOW-UP MESSAGES: The ticket body may include CONVERSATION HISTORY from earlier exchanges.
Use that context to understand the user's intent. For example, if the previous message asked about a booking
and the new message says "what about quote 009?", the user wants the same kind of lookup for quote QT-009.
Treat follow-ups as complete requests informed by context — do NOT escalate just because the message is short."""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def search_knowledge(query: str) -> str:
    """Search the AQUA/SpotOn knowledge base (Cortex Search) for documentation, guides, and rules."""
    payload = json.dumps({
        "query": query,
        "columns": ["chunk", "relative_path", "file_type"],
        "limit": 5,
    })
    sql = f"""SELECT PARSE_JSON(
        SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
            '{fq(SEARCH_SERVICE)}',
            '{_sql_literal(payload)}'
        )
    )['results'] AS results"""
    rows = run_sql(sql)
    if not rows or not rows[0].get("RESULTS"):
        return json.dumps({"found": False, "message": "No documentation found"})
    results = json.loads(rows[0]["RESULTS"])
    passages = []
    for i, r in enumerate(results, 1):
        passages.append({
            "id": f"DOC-{i:03d}",
            "source": r.get("relative_path", "unknown"),
            "file_type": r.get("file_type", "unknown"),
            "excerpt": r.get("chunk", "")[:800],
        })
    return json.dumps({"found": True, "passages": passages})


@tool
def investigate_quote(quote_id: str) -> str:
    """Look up a quote and its related price line and route details."""
    sql = f"""
    SELECT q.*, pl.line_id, pl.rate_20, pl.rate_40, pl.rate_40hc, pl.rate_45,
           pl.status AS line_status, pl.valid_from, pl.valid_to, pl.currency,
           pl.charge_auto, pl.line_flexibility, pl.soc_flag, pl.haz_flag, pl.strategy,
           r.pol, r.pol_name, r.pod, r.pod_name, r.service_line,
           pls.pricelist_name, pls.pricer_name
    FROM {fq('QUOTES')} q
    LEFT JOIN {fq('PRICE_LINES')} pl ON q.line_id = pl.line_id
    LEFT JOIN {fq('ROUTES')} r ON q.route_id = r.route_id
    LEFT JOIN {fq('PRICE_LISTS')} pls ON pl.pricelist_id = pls.pricelist_id
    WHERE q.quote_id = ?
    """
    rows = run_sql(sql, [quote_id])
    if not rows:
        return json.dumps({"found": False, "quote_id": quote_id})
    return json.dumps({"found": True, "data": rows[0]}, default=str)


@tool
def investigate_booking(booking_id: str) -> str:
    """Look up a booking and its related quote, price line, and route."""
    sql = f"""
    SELECT b.*, q.quote_id, q.quoted_rate, q.quoted_at, q.valid_until, q.status AS quote_status,
           pl.line_id, pl.rate_20, pl.rate_40, pl.rate_40hc, pl.status AS line_status,
           pl.valid_from AS line_valid_from, pl.valid_to AS line_valid_to,
           r.pol, r.pol_name, r.pod, r.pod_name
    FROM {fq('BOOKINGS')} b
    LEFT JOIN {fq('QUOTES')} q ON b.quote_id = q.quote_id
    LEFT JOIN {fq('PRICE_LINES')} pl ON q.line_id = pl.line_id
    LEFT JOIN {fq('ROUTES')} r ON b.route_id = r.route_id
    WHERE b.booking_id = ?
    """
    rows = run_sql(sql, [booking_id])
    if not rows:
        return json.dumps({"found": False, "booking_id": booking_id})
    return json.dumps({"found": True, "data": rows[0]}, default=str)


@tool
def lookup_price_line(line_id: str) -> str:
    """Look up a specific price line with its pricelist and route context."""
    sql = f"""
    SELECT pl.*, pls.pricelist_name, pls.pricer_name, pls.status AS pricelist_status,
           r.pol, r.pol_name, r.pod, r.pod_name, r.service_line
    FROM {fq('PRICE_LINES')} pl
    LEFT JOIN {fq('PRICE_LISTS')} pls ON pl.pricelist_id = pls.pricelist_id
    LEFT JOIN {fq('ROUTES')} r ON pl.route_id = r.route_id
    WHERE pl.line_id = ?
    """
    rows = run_sql(sql, [line_id])
    if not rows:
        return json.dumps({"found": False, "line_id": line_id})
    return json.dumps({"found": True, "data": rows[0]}, default=str)


@tool
def search_routes(pol: str = "", pod: str = "") -> str:
    """Search maritime routes by port of loading and/or port of discharge."""
    conditions, params = [], []
    if pol:
        conditions.append("(pol ILIKE ? OR pol_name ILIKE ?)")
        params += [f"%{pol}%", f"%{pol}%"]
    if pod:
        conditions.append("(pod ILIKE ? OR pod_name ILIKE ?)")
        params += [f"%{pod}%", f"%{pod}%"]
    where = " AND ".join(conditions) if conditions else "1=1"
    rows = run_sql(f"SELECT * FROM {fq('ROUTES')} WHERE {where}", params)
    return json.dumps({"found": len(rows) > 0, "count": len(rows), "routes": rows}, default=str)


@tool
def find_similar_tickets(category: str, route_id: str = "") -> str:
    """Find recent tickets with the same category and optionally the same route."""
    conditions, params = ["category = ?"], [category]
    if route_id:
        conditions.append("related_route_id = ?")
        params.append(route_id)
    where = " AND ".join(conditions)
    sql = f"""
    SELECT ticket_id, subject, category, priority, status, created_at, related_route_id
    FROM {fq('TICKETS')}
    WHERE {where}
    ORDER BY created_at DESC
    LIMIT 10
    """
    rows = run_sql(sql, params)
    return json.dumps({"count": len(rows), "tickets": rows}, default=str)


@tool
def get_ticket(ticket_id: str) -> str:
    """Retrieve full details of a support ticket."""
    rows = run_sql(f"SELECT * FROM {fq('TICKETS')} WHERE ticket_id = ?", [ticket_id])
    if not rows:
        return json.dumps({"found": False, "ticket_id": ticket_id})
    return json.dumps({"found": True, "data": rows[0]}, default=str)


@tool
def lookup_price_list(pricelist_id: str = "", pricelist_name: str = "", pricer_name: str = "") -> str:
    """Look up price lists by ID, name, or pricer. Returns matching price lists with their lines count."""
    conditions, params = [], []
    if pricelist_id:
        conditions.append("pls.pricelist_id = ?")
        params.append(pricelist_id)
    if pricelist_name:
        conditions.append("pls.pricelist_name ILIKE ?")
        params.append(f"%{pricelist_name}%")
    if pricer_name:
        conditions.append("pls.pricer_name ILIKE ?")
        params.append(f"%{pricer_name}%")
    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
    SELECT pls.*, COUNT(pl.line_id) AS line_count
    FROM {fq('PRICE_LISTS')} pls
    LEFT JOIN {fq('PRICE_LINES')} pl ON pls.pricelist_id = pl.pricelist_id
    WHERE {where}
    GROUP BY pls.pricelist_id, pls.pricelist_name, pls.pricer_name,
             pls.pricing_group, pls.service_line, pls.status, pls.created_at, pls.updated_at
    ORDER BY pls.updated_at DESC
    LIMIT 10
    """
    rows = run_sql(sql, params)
    if not rows:
        return json.dumps({"found": False, "message": "No price lists match the criteria"})
    return json.dumps({"found": True, "count": len(rows), "price_lists": rows}, default=str)


@tool
def search_tickets(status: str = "", category: str = "", keyword: str = "", limit: int = 10) -> str:
    """Search support tickets by status, category, or keyword in subject/body."""
    conditions, params = [], []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if keyword:
        conditions.append("(subject ILIKE ? OR body ILIKE ?)")
        params += [f"%{keyword}%", f"%{keyword}%"]
    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
    SELECT ticket_id, subject, category, priority, status, created_at,
           related_quote_id, related_booking_id, related_route_id
    FROM {fq('TICKETS')}
    WHERE {where}
    ORDER BY created_at DESC
    LIMIT {max(1, min(int(limit), 20))}
    """
    rows = run_sql(sql, params)
    return json.dumps({"count": len(rows), "tickets": rows}, default=str)


@tool
def search_price_lines(route_id: str = "", pricelist_id: str = "", status: str = "") -> str:
    """Search price lines by route, price list, or status. Returns rates and validity info."""
    conditions, params = [], []
    if route_id:
        conditions.append("pl.route_id = ?")
        params.append(route_id)
    if pricelist_id:
        conditions.append("pl.pricelist_id = ?")
        params.append(pricelist_id)
    if status:
        conditions.append("pl.status = ?")
        params.append(status)
    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
    SELECT pl.*, r.pol, r.pol_name, r.pod, r.pod_name,
           pls.pricelist_name, pls.pricer_name
    FROM {fq('PRICE_LINES')} pl
    LEFT JOIN {fq('ROUTES')} r ON pl.route_id = r.route_id
    LEFT JOIN {fq('PRICE_LISTS')} pls ON pl.pricelist_id = pls.pricelist_id
    WHERE {where}
    ORDER BY pl.valid_from DESC
    LIMIT 15
    """
    rows = run_sql(sql, params)
    return json.dumps({"found": len(rows) > 0, "count": len(rows), "price_lines": rows}, default=str)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    ticket_id: str
    ticket_subject: str
    ticket_body: str
    category: str
    route: str
    triage_reasoning: str
    search_query: str
    needs_quote: bool
    needs_booking: bool
    needs_price_line: bool
    related_quote_id: str
    related_booking_id: str
    related_route_id: str
    related_line_id: str
    related_pricelist_id: str
    related_ticket_id: str
    clarification_question: str
    knowledge_results: str
    data_results: str
    similar_tickets: str
    answer: str
    escalated: bool
    escalation_reason: str
    kb_healing_proposal: str
    tool_ids: list[str]
    messages: Annotated[list[BaseMessage], add_messages]
    trace: list[dict]


def append_trace(state: AgentState, node: str, detail: str) -> list[dict]:
    existing = list(state.get("trace", []))
    existing.append({"node": node, "detail": detail, "ts": datetime.now().isoformat()})
    return existing


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(llm: ChatOpenAI | None = None):
    if llm is None:
        llm = make_llm()

    router_llm = llm.with_structured_output(TriageDecision)

    knowledge_tools = [search_knowledge]
    data_tools = [investigate_quote, investigate_booking, lookup_price_line, lookup_price_list, search_price_lines, search_routes, get_ticket, search_tickets, find_similar_tickets]

    def tool_calls(calls):
        ids = [uuid4().hex for _ in calls]
        msg = AIMessage(content="", tool_calls=[
            {"name": n, "args": a, "id": i} for (n, a), i in zip(calls, ids)
        ])
        return ids, msg

    def triage(state: AgentState) -> dict:
        ticket_text = f"Subject: {state.get('ticket_subject','')}\nBody: {state.get('ticket_body','')}"
        decision: TriageDecision = router_llm.invoke([
            {"role": "system", "content": TRIAGE_SYSTEM},
            {"role": "user", "content": ticket_text},
        ])
        quote_id = decision.extracted_quote_id or state.get("related_quote_id", "")
        booking_id = decision.extracted_booking_id or state.get("related_booking_id", "")
        route_id = decision.extracted_route_id or state.get("related_route_id", "")
        line_id = decision.extracted_line_id or state.get("related_line_id", "")
        pricelist_id = decision.extracted_pricelist_id or state.get("related_pricelist_id", "")
        ticket_id = decision.extracted_ticket_id or state.get("related_ticket_id", "")

        # Force route to 'data' if any ID was extracted
        has_any_id = any([quote_id, booking_id, route_id, line_id, pricelist_id, ticket_id])
        route = decision.route
        if has_any_id and route in ("clarify", "escalate"):
            route = "data"

        return {
            "category": decision.category,
            "route": route,
            "triage_reasoning": decision.reasoning,
            "needs_quote": decision.needs_quote or bool(quote_id),
            "needs_booking": decision.needs_booking or bool(booking_id),
            "needs_price_line": decision.needs_price_line or bool(line_id),
            "search_query": decision.search_query or state.get("ticket_subject", ""),
            "related_quote_id": quote_id,
            "related_booking_id": booking_id,
            "related_route_id": route_id,
            "related_line_id": line_id,
            "related_pricelist_id": pricelist_id,
            "related_ticket_id": ticket_id,
            "clarification_question": decision.clarification_question or "",
            "trace": append_trace(state, "triage",
                f"category={decision.category} route={route} reasoning={decision.reasoning}"
                f" extracted_ids=quote:{quote_id},booking:{booking_id},route:{route_id},line:{line_id},ticket:{ticket_id}"),
        }

    def knowledge_agent(state: AgentState) -> dict:
        query = state.get("search_query", state.get("ticket_subject", ""))
        calls_list = [("search_knowledge", {"query": query})]
        ids, msg = tool_calls(calls_list)
        tool_node = ToolNode(knowledge_tools)
        result_state = tool_node.invoke({"messages": [msg]})
        result_msgs = result_state["messages"]
        knowledge_text = ""
        for m in result_msgs:
            if isinstance(m, ToolMessage):
                knowledge_text = m.content
        return {
            "knowledge_results": knowledge_text,
            "messages": [msg] + result_msgs,
            "tool_ids": ids,
            "trace": append_trace(state, "knowledge_agent", f"query='{query}' results_len={len(knowledge_text)}"),
        }

    def data_agent(state: AgentState) -> dict:
        ticket_text = f"Subject: {state.get('ticket_subject','')}\nBody: {state.get('ticket_body','')}"
        quote_id = state.get("related_quote_id", "")
        booking_id = state.get("related_booking_id", "")
        route_id = state.get("related_route_id", "")
        line_id = state.get("related_line_id", "")
        pricelist_id = state.get("related_pricelist_id", "")
        ticket_id = state.get("related_ticket_id", "")

        system_msg = f"""You are a data lookup agent for AQUA/SpotOn maritime pricing support.
Given the user's question, call the appropriate tools to retrieve the needed data.

TICKET: {ticket_text}
TRIAGE: category={state.get('category','')} reasoning={state.get('triage_reasoning','')}
KNOWN IDs: quote_id={quote_id}, booking_id={booking_id}, route_id={route_id}, line_id={line_id}, pricelist_id={pricelist_id}, ticket_id={ticket_id}

Call one or more tools to gather the relevant operational data. If an ID is provided, use it directly.
IMPORTANT: After getting results, if the data references other IDs (e.g. a booking references a quote_id or line_id,
a quote references a route_id or pricelist_id), make follow-up tool calls to get that related data too.
Build a complete picture — don't stop at one lookup if more context would help answer the question."""

        data_llm = llm.bind_tools(data_tools)
        messages = [{"role": "system", "content": system_msg}]
        all_tool_names = []
        all_data_texts = []
        all_msg_objects = []

        for _round in range(3):  # up to 3 rounds of tool calls
            response = data_llm.invoke(messages)

            if not response.tool_calls:
                break

            # Use the response AIMessage directly — it has correct tool_call IDs
            tool_node = ToolNode(data_tools)
            result_state = tool_node.invoke({"messages": [response]})
            result_msgs = result_state["messages"]

            for m in result_msgs:
                if isinstance(m, ToolMessage):
                    all_data_texts.append(m.content)

            all_tool_names.extend(tc["name"] for tc in response.tool_calls)
            all_msg_objects.extend([response] + result_msgs)

            # Feed results back as LangChain message objects for next round
            messages.append(response)
            messages.extend(m for m in result_msgs if isinstance(m, ToolMessage))

        if not all_data_texts:
            return {
                "data_results": json.dumps({"found": False, "message": "No data lookups needed based on the question"}),
                "trace": append_trace(state, "data_agent", "no tool calls made"),
            }

        combined = "\n---\n".join(all_data_texts)
        return {
            "data_results": combined,
            "messages": all_msg_objects,
            "tool_ids": [],
            "trace": append_trace(state, "data_agent", f"tools={all_tool_names} rounds={_round+1} results_len={len(combined)}"),
        }

    def check_similar(state: AgentState) -> dict:
        category = state.get("category", "UNKNOWN")
        route_id = state.get("related_route_id", "")
        result = find_similar_tickets.invoke({"category": category, "route_id": route_id})
        return {
            "similar_tickets": result,
            "trace": append_trace(state, "check_similar", f"category={category} route={route_id}"),
        }

    def resolution_agent(state: AgentState) -> dict:
        knowledge = state.get("knowledge_results", "")
        data = state.get("data_results", "")
        similar = state.get("similar_tickets", "")
        ticket_text = f"Subject: {state.get('ticket_subject','')}\nBody: {state.get('ticket_body','')}"

        prompt = f"""You are a hypercare support resolution agent for AQUA/SpotOn maritime pricing.

TICKET:
{ticket_text}

TRIAGE ANALYSIS:
Category: {state.get('category','')}
Reasoning: {state.get('triage_reasoning','')}

DOCUMENTATION FOUND:
{knowledge if knowledge else 'No documentation searched.'}

OPERATIONAL DATA:
{data if data else 'No operational data retrieved.'}

SIMILAR RECENT TICKETS:
{similar if similar else 'None found.'}

RULES:
1. Answer ONLY based on the evidence above. Cite sources as [DOC-XXX: filename] for documentation or [DATA: TABLENAME] for operational data (e.g. [DATA: BOOKINGS], [DATA: QUOTES], [DATA: PRICE_LINES], [DATA: ROUTES]).
2. If documentation and data contradict each other, flag the contradiction explicitly.
3. If evidence is insufficient to answer, say so and recommend escalation to the Pricing team.
4. Never invent a reason for a price difference. Absence of proof must appear clearly.
5. For price mismatches, compare the quoted_rate with the line rate for the matching container type.
6. Distinguish between AQUA rules (pricer-facing) and SpotOn rules (customer-facing).


Provide your response in this JSON format:
{{"resolved": true/false, "confidence": "high/medium/low", "answer": "...", "sources_cited": [...], "escalation_reason": "..." (if not resolved)}}"""

        response = llm.invoke(prompt)
        content = response.content

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            result = json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            result = {"resolved": False, "confidence": "low", "answer": content,
                      "sources_cited": [], "escalation_reason": "Could not parse resolution"}

        resolved = result.get("resolved", False)
        answer = result.get("answer", "")
        sources = result.get("sources_cited", [])
        escalation_reason = result.get("escalation_reason", "")

        answer_with_meta = (
            f"**Resolution** (confidence: {result.get('confidence','unknown')}):\n\n"
            f"{answer}\n\n"
            f"**Sources:** {', '.join(str(s) for s in sources) if sources else 'none'}"
        )

        return {
            "answer": answer_with_meta,
            "escalated": not resolved,
            "escalation_reason": escalation_reason if not resolved else "",
            "trace": append_trace(state, "resolution_agent",
                f"resolved={resolved} confidence={result.get('confidence','')} escalated={not resolved}"),
        }

    def escalation(state: AgentState) -> dict:
        reason = state.get("escalation_reason", "Insufficient evidence")
        answer = state.get("answer", "")
        escalation_msg = (
            f"**ESCALATION TO PRICING TEAM**\n\n"
            f"Ticket: {state.get('ticket_id','')}\n"
            f"Category: {state.get('category','')}\n"
            f"Reason: {reason}\n\n"
            f"Partial findings:\n{answer}\n\n"
            f"Please review and provide additional context."
        )
        return {
            "answer": escalation_msg,
            "trace": append_trace(state, "escalation", f"reason={reason}"),
        }

    def kb_healing_agent(state: AgentState) -> dict:
        similar = state.get("similar_tickets", "")
        try:
            similar_data = json.loads(similar) if similar else {"count": 0}
        except json.JSONDecodeError:
            similar_data = {"count": 0}

        proposal = None
        if similar_data.get("count", 0) >= 2:
            category = state.get("category", "")
            ticket_subject = state.get("ticket_subject", "")
            knowledge = state.get("knowledge_results", "")

            prompt = f"""You are a knowledge base maintenance agent. Analyze whether the knowledge base
has a gap that needs fixing.

RECURRING TICKET PATTERN:
Category: {category}
Current ticket subject: {ticket_subject}
Number of similar tickets found: {similar_data['count']}
Similar tickets: {json.dumps(similar_data.get('tickets', [])[:5], default=str)}

CURRENT KB COVERAGE for this topic:
{knowledge if knowledge else 'No relevant documentation found.'}

If there is a documentation gap (missing answer, outdated info, or contradiction), produce a JSON proposal:
{{"gap_detected": true/false, "description": "...", "affected_tickets": [...], "suggested_update": "...", "target_section": "..."}}

If the KB adequately covers this topic, return {{"gap_detected": false}}"""

            response = llm.invoke(prompt)
            content = response.content
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                proposal = json.loads(content.strip())
            except (json.JSONDecodeError, IndexError):
                proposal = {"gap_detected": False, "parse_error": True}

        return {
            "kb_healing_proposal": json.dumps(proposal, default=str) if proposal else "",
            "trace": append_trace(state, "kb_healing_agent",
                f"similar_count={similar_data.get('count',0)} gap_detected={proposal.get('gap_detected',False) if proposal else False}"),
        }

    def route_after_triage(state: AgentState) -> str:
        route = state.get("route", "escalate")
        if route == "knowledge":
            return "knowledge"
        elif route == "data":
            return "data"
        elif route == "both":
            return "both_knowledge"
        elif route == "clarify":
            return "clarify"
        else:
            return "escalate_direct"

    def route_after_resolution(state: AgentState) -> str:
        if state.get("escalated"):
            return "escalation"
        return "kb_healing"

    graph = StateGraph(AgentState)

    graph.add_node("triage", triage)
    graph.add_node("knowledge_agent", knowledge_agent)
    graph.add_node("data_agent", data_agent)
    graph.add_node("both_knowledge", knowledge_agent)
    graph.add_node("both_data", data_agent)
    graph.add_node("check_similar", check_similar)
    graph.add_node("resolution_agent", resolution_agent)
    graph.add_node("escalation", escalation)
    graph.add_node("kb_healing_agent", kb_healing_agent)
    graph.add_node("escalate_direct", lambda s: {
        "answer": f"**ESCALATION**: Ticket requires human review.\nReason: {s.get('triage_reasoning','')}",
        "escalated": True,
        "trace": append_trace(s, "escalate_direct", s.get("triage_reasoning", "")),
    })
    graph.add_node("clarify", lambda s: {
        "answer": s.get("clarification_question", "Could you provide more details about your request?"),
        "escalated": False,
        "trace": append_trace(s, "clarify", s.get("clarification_question", "")),
    })

    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, {
        "knowledge": "knowledge_agent",
        "data": "data_agent",
        "both_knowledge": "both_knowledge",
        "clarify": "clarify",
        "escalate_direct": "escalate_direct",
    })

    graph.add_edge("knowledge_agent", "check_similar")
    graph.add_edge("check_similar", "resolution_agent")
    graph.add_edge("data_agent", "check_similar")
    graph.add_edge("both_knowledge", "both_data")
    graph.add_edge("both_data", "check_similar")

    graph.add_conditional_edges("resolution_agent", route_after_resolution, {
        "escalation": "escalation",
        "kb_healing": "kb_healing_agent",
    })

    graph.add_edge("escalation", "kb_healing_agent")
    graph.add_edge("kb_healing_agent", END)
    graph.add_edge("escalate_direct", END)
    graph.add_edge("clarify", END)

    return graph.compile(checkpointer=InMemorySaver())


# ---------------------------------------------------------------------------
# Convenience: process a ticket
# ---------------------------------------------------------------------------

def process_ticket(graph, ticket_id: str = None, subject: str = "", body: str = "",
                   quote_id: str = "", booking_id: str = "", route_id: str = "") -> dict:
    config = {"configurable": {"thread_id": uuid4().hex}}
    initial = {
        "ticket_id": ticket_id or "",
        "ticket_subject": subject,
        "ticket_body": body,
        "related_quote_id": quote_id,
        "related_booking_id": booking_id,
        "related_route_id": route_id,
        "messages": [],
        "trace": [],
    }
    result = graph.invoke(initial, config=config)
    return result


def process_ticket_from_db(graph, ticket_id: str) -> dict:
    rows = run_sql(f"SELECT * FROM {fq('TICKETS')} WHERE ticket_id = ?", [ticket_id])
    if not rows:
        raise ValueError(f"Ticket {ticket_id} not found")
    t = rows[0]
    return process_ticket(
        graph,
        ticket_id=ticket_id,
        subject=t.get("SUBJECT", ""),
        body=t.get("BODY", ""),
        quote_id=t.get("RELATED_QUOTE_ID") or "",
        booking_id=t.get("RELATED_BOOKING_ID") or "",
        route_id=t.get("RELATED_ROUTE_ID") or "",
    )


def format_trace(result: dict) -> str:
    lines = []
    for step in result.get("trace", []):
        lines.append(f"[{step['node']}] {step['detail']}")
    return "\n".join(lines)
