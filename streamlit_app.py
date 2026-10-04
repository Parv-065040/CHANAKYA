import streamlit as st
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.server import App


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="CHANAKYA",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CSS
# ============================================================

st.markdown("""
<style>
    .stApp {
        background: #080b12;
        color: #e8edf5;
    }

    section[data-testid="stSidebar"] {
        background: #0d111a;
        border-right: 1px solid #202735;
    }

    section[data-testid="stSidebar"] * {
        color: #dce3ee;
    }

    .brand {
        font-size: 28px;
        font-weight: 800;
        letter-spacing: 2px;
        color: #ffffff;
        margin-bottom: 2px;
    }

    .brand-sub {
        color: #7f8ba0;
        font-size: 12px;
        margin-bottom: 28px;
    }

    .hero {
        padding: 42px 10px 25px 10px;
    }

    .hero h1 {
        font-size: 52px;
        line-height: 1.05;
        margin: 0;
        color: #ffffff;
        font-weight: 800;
    }

    .hero h1 span {
        color: #6ea8fe;
    }

    .hero p {
        color: #9ba8bb;
        font-size: 17px;
        max-width: 850px;
        line-height: 1.7;
        margin-top: 18px;
    }

    .card {
        background: #10151f;
        border: 1px solid #202837;
        border-radius: 14px;
        padding: 22px;
        margin-bottom: 16px;
    }

    .card-title {
        font-size: 18px;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 8px;
    }

    .muted {
        color: #8995a8;
        line-height: 1.65;
    }

    .metric {
        background: #10151f;
        border: 1px solid #202837;
        border-radius: 12px;
        padding: 18px;
        text-align: center;
    }

    .metric-value {
        font-size: 26px;
        font-weight: 800;
        color: #ffffff;
    }

    .metric-label {
        color: #7f8ba0;
        font-size: 12px;
        margin-top: 5px;
    }

    .answer-box {
        background: #10151f;
        border: 1px solid #283246;
        border-radius: 14px;
        padding: 22px;
        margin-top: 12px;
    }

    .answer-title {
        font-size: 14px;
        color: #6ea8fe;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 12px;
    }

    .status-ok {
        color: #66d19e;
        font-weight: 700;
    }

    .small {
        font-size: 12px;
        color: #7f8ba0;
    }

    div[data-testid="stChatMessage"] {
        border-radius: 12px;
    }

    .stButton button {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# APP
# ============================================================

@st.cache_resource
def get_app():
    return App()


try:
    app = get_app()
except Exception as e:
    st.error("CHANAKYA backend could not start.")
    st.exception(e)
    st.stop()


# ============================================================
# SESSION STATE
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "department" not in st.session_state:
    st.session_state.department = "All Departments"

if "page" not in st.session_state:
    st.session_state.page = "Home"


# ============================================================
# HELPERS
# ============================================================

def clean_answer(text):
    if text is None:
        return ""

    text = str(text)

    # Convert markdown bold to normal markdown-friendly text.
    # We use st.markdown for answers, so markdown remains valid.
    return text.strip()


def is_followup_question(question):
    q = question.lower().strip()

    followup_patterns = [
        r"\bwhat about\b",
        r"\bhow about\b",
        r"\bwhat was the previous\b",
        r"\bprevious year\b",
        r"\bprevious one\b",
        r"\bthat\b",
        r"\bthis\b",
        r"\bit\b",
        r"\bthey\b",
        r"\bthose\b",
        r"\bcompare\b",
        r"\bcompared with\b",
        r"\bcompared to\b",
        r"\bsame\b",
        r"\bmore than\b",
        r"\bless than\b",
    ]

    return any(re.search(pattern, q) for pattern in followup_patterns)


def rewrite_followup(question):
    """
    Only rewrite genuine follow-up questions.

    Standalone questions MUST go directly to the backend.
    This prevents conversation history from contaminating retrieval.
    """

    if not is_followup_question(question):
        return question

    previous = st.session_state.messages[-8:]

    if not previous:
        return question

    history_lines = []

    for msg in previous:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))

        if role == "user":
            history_lines.append("User: " + content)
        elif role == "assistant":
            history_lines.append("CHANAKYA: " + content)

    history = "\n".join(history_lines)

    prompt = f"""
Rewrite the user's latest question as ONE standalone question.

Use the conversation only to resolve references such as:
- previous year
- that value
- this figure
- compare it
- the same metric

Do NOT answer the question.
Do NOT add facts.
Do NOT invent entities, numbers, dates, or departments.
Do NOT include conversation history in the rewritten question.

Conversation:
{history}

Latest user question:
{question}

Return ONLY the standalone question.
"""

    try:
        rewritten = app.llm.complete(prompt)
        rewritten = str(rewritten).strip()

        if rewritten and len(rewritten) < 1000:
            return rewritten
    except Exception:
        pass

    return question


def get_result_value(result, name, default=None):
    if hasattr(result, name):
        return getattr(result, name)

    if isinstance(result, dict):
        return result.get(name, default)

    return default


def render_result(result):
    answer = get_result_value(result, "answer", "")
    evidence = get_result_value(result, "evidence", [])
    calculations = get_result_value(result, "calculations", [])

    st.markdown(
        '<div class="answer-box">',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="answer-title">CHANAKYA Answer</div>',
        unsafe_allow_html=True,
    )

    st.markdown(clean_answer(answer))

    st.markdown("</div>", unsafe_allow_html=True)

    if calculations:
        with st.expander("Calculations", expanded=False):
            if isinstance(calculations, (list, tuple)):
                for item in calculations:
                    st.write(item)
            else:
                st.write(calculations)

    if evidence:
        with st.expander("Evidence & Sources", expanded=False):
            if isinstance(evidence, (list, tuple)):
                for i, item in enumerate(evidence, 1):
                    st.markdown(f"**Evidence {i}**")
                    st.write(item)
                    if i != len(evidence):
                        st.divider()
            else:
                st.write(evidence)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        '<div class="brand">CHANAKYA</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="brand-sub">Agentic Enterprise Knowledge Platform</div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Navigation")

    if st.button("⌂  Home", use_container_width=True):
        st.session_state.page = "Home"
        st.rerun()

    if st.button("◉  Chat", use_container_width=True):
        st.session_state.page = "Chat"
        st.rerun()

    st.divider()

    st.markdown("### Department")

    departments = [
        "All Departments",
        "Finance",
        "HR",
        "Manufacturing",
        "Customer Support",
    ]

    selected = st.selectbox(
        "Department",
        departments,
        index=departments.index(st.session_state.department)
        if st.session_state.department in departments
        else 0,
        label_visibility="collapsed",
    )

    st.session_state.department = selected

    st.divider()

    st.markdown("### System Status")

    st.markdown(
        '<span class="status-ok">● System Online</span>',
        unsafe_allow_html=True,
    )

    try:
        docs = len(app.kb.documents)
    except Exception:
        docs = "—"

    try:
        chunks = len(app.kb.chunks)
    except Exception:
        chunks = "—"

    st.caption(f"Documents: {docs}")
    st.caption(f"Chunks: {chunks}")
    st.caption("Retrieval: Hybrid")
    st.caption("Embeddings: BGE-M3")
    st.caption("LLM: GPT-OSS 120B")

    st.divider()

    if st.button("＋ New Conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    if st.session_state.messages:
        st.caption(
            f"Conversation memory: {len(st.session_state.messages)} messages"
        )


# ============================================================
# HOME
# ============================================================

if st.session_state.page == "Home":

    st.markdown(
        """
        <div class="hero">
            <h1>Enterprise intelligence,<br><span>grounded in evidence.</span></h1>
            <p>
                CHANAKYA is an agentic enterprise knowledge and business
                automation platform designed to answer business questions
                using governed documents, structured tables, numerical
                reasoning, hybrid retrieval and evidence-backed citations.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(
            """
            <div class="metric">
                <div class="metric-value">16</div>
                <div class="metric-label">Enterprise Documents</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            """
            <div class="metric">
                <div class="metric-value">1,125+</div>
                <div class="metric-label">Knowledge Chunks</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            """
            <div class="metric">
                <div class="metric-value">4</div>
                <div class="metric-label">Departments</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            """
            <div class="metric">
                <div class="metric-value">130</div>
                <div class="metric-label">Evaluation Questions</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">What CHANAKYA does</div>
                <div class="muted">
                    • Understands business questions<br>
                    • Routes questions to the right reasoning path<br>
                    • Searches enterprise knowledge using hybrid retrieval<br>
                    • Handles tables and numerical reasoning<br>
                    • Produces evidence-backed answers<br>
                    • Refuses when sufficient evidence is unavailable
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">Enterprise Coverage</div>
                <div class="muted">
                    <b>Finance</b> — reports, budgets and controls<br>
                    <b>HR</b> — policies, compensation and performance<br>
                    <b>Manufacturing</b> — production, quality and maintenance<br>
                    <b>Customer Support</b> — tickets, SLAs and escalation
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class="card">
            <div class="card-title">Designed for business reasoning</div>
            <div class="muted">
                CHANAKYA is not simply a document chatbot. It separates
                retrieval, numerical/table reasoning, answer generation and
                grounding validation so that business answers remain traceable
                to the underlying enterprise evidence.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.info("Open Chat from the sidebar to start asking questions.")


# ============================================================
# CHAT
# ============================================================

else:

    st.title("CHANAKYA Chat")

    st.caption(
        f"Department: {st.session_state.department}  •  "
        "Answers are grounded in the CHANAKYA knowledge base."
    )

    st.divider()

    # Existing conversation
    for msg in st.session_state.messages:

        role = msg.get("role")

        if role == "user":
            with st.chat_message("user"):
                st.markdown(msg.get("content", ""))

        elif role == "assistant":
            with st.chat_message("assistant"):

                answer = msg.get("content", "")
                st.markdown(answer)

                evidence = msg.get("evidence", [])
                calculations = msg.get("calculations", [])

                if calculations:
                    with st.expander("Calculations", expanded=False):
                        if isinstance(calculations, (list, tuple)):
                            for item in calculations:
                                st.write(item)
                        else:
                            st.write(calculations)

                if evidence:
                    with st.expander("Evidence & Sources", expanded=False):
                        if isinstance(evidence, (list, tuple)):
                            for i, item in enumerate(evidence, 1):
                                st.markdown(f"**Evidence {i}**")
                                st.write(item)
                        else:
                            st.write(evidence)

    prompt = st.chat_input("Ask CHANAKYA a question...")

    if prompt:

        # ----------------------------------------------------
        # USER MESSAGE
        # ----------------------------------------------------

        st.session_state.messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        # ----------------------------------------------------
        # CRITICAL:
        # Standalone questions go DIRECTLY to retrieval.
        #
        # We do NOT append the entire chat history to the query.
        # This was the reason simple questions such as
        # "What was the company total revenue?" were failing.
        # ----------------------------------------------------

        standalone_question = rewrite_followup(prompt)

        try:
            result = app.orch.ask(
                standalone_question,
                department=(
                    None
                    if st.session_state.department == "All Departments"
                    else st.session_state.department
                ),
            )

            answer = get_result_value(result, "answer", "")
            evidence = get_result_value(result, "evidence", [])
            calculations = get_result_value(result, "calculations", [])

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": clean_answer(answer),
                    "evidence": evidence,
                    "calculations": calculations,
                }
            )

        except Exception as e:

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "I encountered an error while processing the "
                        "question. Please try again."
                    ),
                    "evidence": [],
                    "calculations": [],
                }
            )

            st.error(str(e))

        st.rerun()


