import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp, BookOpenText, CaretDown, CheckCircle, CircleNotch,
  Cpu, Database, FileText, Funnel, Gauge, Graph, House, LinkSimple,
  MagnifyingGlass, Plus, Pulse, ShieldCheck, Sparkle, Stack, X
} from "@phosphor-icons/react";
import { ChanakyaOrb } from "./components/ChanakyaOrb";
import { MagicCard } from "./components/MagicCard";
import { ProjectScene } from "./components/ProjectScene";
import { DocumentViewer } from "./components/DocumentViewer";

const API = import.meta.env.VITE_API_URL || "";

const departments = [
  { name: "", label: "All departments" },
  { name: "finance", label: "Finance" },
  { name: "hr", label: "Human Resources" },
  { name: "manufacturing", label: "Manufacturing" },
  { name: "customer_support", label: "Customer Support" },
];

const suggestions = [
  "What was revenue in FY2025 and how much did it grow from FY2024?",
  "What was employee attrition in FY2025 compared with FY2024?",
  "Which production line had the highest defect rate?",
  "What is the SLA for Priority-1 incidents?",
  "Did increased production volume coincide with higher defect rates in Q2?",
  "Calculate the percentage increase in EBITDA between FY2024 and FY2025.",
];

const navItems = [
  { id: "home", label: "Overview", icon: House },
  { id: "workspace", label: "Ask CHANAKYA", icon: Sparkle },
  { id: "knowledge", label: "Knowledge", icon: Stack },
];

function App() {
  const [activeTab, setActiveTab] = useState("home");
  const [department, setDepartment] = useState("");
  const [health, setHealth] = useState(null);
  const [docs, setDocs] = useState([]);
  const [evaluation, setEvaluation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [viewer, setViewer] = useState(null);
  const [error, setError] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(true);
  const inputRef = useRef(null);
  const logRef = useRef(null);

  const refreshSystem = async () => {
    try {
      const [h, d, e] = await Promise.all([
        fetch(API + "/health").then((r) => r.json()),
        fetch(API + "/documents").then((r) => r.json()),
        fetch(API + "/evaluation/summary").then((r) => r.ok ? r.json() : null),
      ]);
      setHealth(h);
      setDocs(Array.isArray(d) ? d.map((doc) => ({ ...doc, chunks: doc.chunks ?? doc.n_chunks ?? 0 })) : []);
      setEvaluation(e);
      setError("");
    } catch {
      setError("CHANAKYA API is not reachable. Keep the backend running on port 8000.");
    }
  };

  useEffect(() => {
    refreshSystem();
    const timer = setInterval(refreshSystem, 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const selectedDepartment = useMemo(
    () => (departments.find((item) => item.name === department) || departments[0]).label,
    [department]
  );

  const ask = async (preset) => {
    const q = (preset ?? question).trim();
    if (!q || loading) return;

    setActiveTab("workspace");
    setQuestion("");
    setError("");
    setShowSuggestions(false);
    const assistantIndex = messages.length + 1;
    setMessages((current) => [
      ...current,
      { role: "user", content: q },
      { role: "assistant", content: "", streaming: true },
    ]);
    setLoading(true);

    try {
      const response = await fetch(API + "/query/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, department: department || null }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.error?.message || "Request failed (" + response.status + ")");
      }
      if (!response.body) throw new Error("Streaming is not available in this browser.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      let finalResult = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        buffer = buffer.replace(/\r\n/g, "\n");
        while (buffer.includes("\n\n")) {
          const index = buffer.indexOf("\n\n");
          const event = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const type = event.match(/event:\s*(\w+)/)?.[1];
          const data = event.match(/data:\s*(.*)/s)?.[1];
          if (!type || data == null) continue;
          const parsed = JSON.parse(data);

          if (type === "token") {
            answer += parsed;
            setMessages((current) => current.map((message, i) =>
              i === assistantIndex ? { ...message, content: answer } : message
            ));
          }
          if (type === "done") finalResult = parsed;
        }
      }

      setMessages((current) => current.map((message, i) =>
        i === assistantIndex
          ? { ...message, content: finalResult?.answer || answer, result: finalResult, streaming: false }
          : message
      ));
    } catch (err) {
      setMessages((current) => current.map((message, i) =>
        i === assistantIndex
          ? { ...message, content: "I couldn't complete that request.", streaming: false, error: err.message }
          : message
      ));
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 40);
      refreshSystem();
    }
  };

  const openSource = async (item) => {
    if (!item?.chunk_id) return;
    setSourceLoading(true);
    setSource(null);
    try {
      const response = await fetch(API + "/sources/" + item.chunk_id);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || "Source unavailable");
      setSource({ ...payload, document: payload.document_name || item.document || "Retrieved source" });
    } catch (err) {
      setSource({ error: err.message });
    } finally {
      setSourceLoading(false);
    }
  };

  const newConversation = () => {
    setMessages([]);
    setShowSuggestions(true);
    setActiveTab("workspace");
    setError("");
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  const openDocument = (doc, page) => setViewer({ doc, page: page || 1 });

  return (
    <div className="app-shell">
      <div className="ambient-grid" aria-hidden="true" />

      <header className="topbar">
        <button className="brand-lockup" onClick={() => setActiveTab("home")} aria-label="CHANAKYA overview">
          <div className="brand-mark"><Sparkle weight="fill" size={15} /></div>
          <div>
            <div className="brand-name">CHANAKYA</div>
            <div className="brand-kicker">Enterprise intelligence platform</div>
          </div>
        </button>

        <nav className="primary-nav" aria-label="Primary navigation">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={activeTab === id ? "nav-item is-active" : "nav-item"} onClick={() => setActiveTab(id)}>
              <Icon size={15} weight={activeTab === id ? "fill" : "regular"} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="topbar-actions">
          <div className="system-pill">
            <span className={"status-dot " + (health?.status === "ok" ? "is-online" : "")} />
            {health?.status === "ok" ? "Operational" : "Connecting"}
          </div>
          <button className="new-chat-button" onClick={newConversation}>
            <Plus size={17} weight="bold" /><span>New chat</span>
          </button>
        </div>
      </header>

      <main className="main-stage">
        {activeTab === "home" && (
          <HomeView health={health} docs={docs} evaluation={evaluation}
            onAsk={(q) => { setActiveTab("workspace"); ask(q); }}
            onKnowledge={() => setActiveTab("knowledge")} />
        )}

        {activeTab === "workspace" && (
          <WorkspaceView department={department} setDepartment={setDepartment}
            selectedDepartment={selectedDepartment} messages={messages} question={question}
            setQuestion={setQuestion} loading={loading} showSuggestions={showSuggestions}
            inputRef={inputRef} logRef={logRef} ask={ask} onSource={openSource} health={health} />
        )}

        {activeTab === "knowledge" && (
          <KnowledgeView docs={docs} department={department} setDepartment={setDepartment} onOpen={openDocument} />
        )}



        {error && <div className="global-error"><X size={16} /> {error}</div>}
      </main>

      {source && (
        <SourceDrawer source={source} loading={sourceLoading} onClose={() => setSource(null)}
          onOpenDocument={() => {
            const doc = docs.find((item) => item.document_id === source.document_id);
            if (doc) setViewer({ doc, page: source.page_start || 1 });
          }} />
      )}

      {viewer && <DocumentViewer document={viewer.doc} page={viewer.page} onClose={() => setViewer(null)} />}
    </div>
  );
}

function HomeView({ health, docs, evaluation, onAsk, onKnowledge }) {
  const departmentCounts = useMemo(() => {
    const counts = {};
    docs.forEach((doc) => { counts[doc.department] = (counts[doc.department] || 0) + 1; });
    return counts;
  }, [docs]);

  return (
    <div className="page page-home">
      <section className="hero-panel">
        <div className="hero-copy">
          <div className="eyebrow"><ShieldCheck size={15} weight="bold" /> Governed enterprise intelligence</div>
          <h1>Ask the business.<br /><span>See the evidence.</span></h1>
          <p>CHANAKYA is an agentic enterprise knowledge layer for Finance, HR, Manufacturing and Customer Support. It routes questions, retrieves evidence, reasons over structured data and validates citations before answering.</p>
          <div className="hero-actions">
            <button className="primary-action" onClick={() => onAsk("What is the most important insight in the enterprise knowledge base?")}><Sparkle size={16} weight="fill" /> Start a governed query</button>
            <button className="secondary-action" onClick={onKnowledge}><Stack size={16} /> Explore knowledge</button>
          </div>
          <div className="trust-row"><span><CheckCircle weight="fill" /> Evidence grounded</span><span><CheckCircle weight="fill" /> Numerical reasoning</span><span><CheckCircle weight="fill" /> Citation validation</span></div>
        </div>
        <div className="hero-visual">
          <div className="hero-visual-label">WISDOM LAYER / ACTIVE</div>
          <ChanakyaOrb />
          <div className="orb-caption"><b>CHANAKYA</b><span>Knowledge → reasoning → evidence</span></div>
        </div>
      </section>

      <section className="metric-grid">
        <MetricCard icon={Database} label="Knowledge base" value={health?.documents ?? docs.length} suffix=" docs" detail={(health?.chunks ?? "—") + " indexed chunks"} />
        <MetricCard icon={Pulse} label="Runtime" value={health?.status === "ok" ? "ONLINE" : "SYNC"} detail={health?.llm === "groq" ? "Groq reasoning enabled" : "Offline verified mode"} />
        <MetricCard icon={ShieldCheck} label="Governance" value={health?.auth === "none" ? "LOCAL" : "TOKEN"} detail={(health?.storage || "local") + " persistence"} />
        <MetricCard icon={Gauge} label="Evaluation" value={evaluation?.accuracy != null ? Math.round(evaluation.accuracy * 100) + "%" : "READY"} detail={evaluation ? "Latest benchmark summary" : "Run evaluation to populate"} />
      </section>

      <section className="home-grid">
        <MagicCard className="architecture-card">
          <div className="section-head"><div><span className="micro-label">SYSTEM MAP</span><h2>From question to evidence</h2></div><span className="live-badge"><span /> live architecture</span></div>
          <ProjectScene />
        </MagicCard>

        <MagicCard className="project-card">
          <div className="section-head"><div><span className="micro-label">PROJECT PROFILE</span><h2>What CHANAKYA is built on</h2></div></div>
          <div className="stack-list">
            <TechRow icon={Cpu} name="Python backend" meta="stdlib HTTP API · orchestration" />
            <TechRow icon={Graph} name="Hybrid retrieval" meta="dense + keyword + fusion" />
            <TechRow icon={Database} name="Local / Supabase" meta="documents, chunks and provenance" />
            <TechRow icon={Sparkle} name="Groq + GPT-OSS" meta="optional grounded generation" />
            <TechRow icon={Stack} name="React + Vite" meta="responsive product interface" />
          </div>
          <div className="department-strip">
            {Object.entries(departmentCounts).map(([key, value]) => <div key={key}><span>{key.replace("_", " ")}</span><b>{value}</b></div>)}
          </div>
        </MagicCard>
      </section>

      <section className="capability-row">
        {[
          ["01", "Route", "Classifies the question and applies department scope."],
          ["02", "Retrieve", "Combines semantic and lexical evidence with rank fusion."],
          ["03", "Reason", "Handles tables, comparisons and numerical calculations."],
          ["04", "Validate", "Checks citations, numbers and evidence coverage."],
        ].map(([number, title, copy]) => (
          <MagicCard className="capability-card" key={number}><span className="capability-number">{number}</span><h3>{title}</h3><p>{copy}</p></MagicCard>
        ))}
      </section>
    </div>
  );
}

function WorkspaceView({ department, setDepartment, selectedDepartment, messages, question, setQuestion, loading, showSuggestions, inputRef, logRef, ask, onSource, health }) {
  return (
    <div className="page page-workspace">
      <div className="workspace-header">
        <div><div className="eyebrow"><Sparkle size={14} weight="fill" /> Governed query workspace</div><h1>Ask CHANAKYA</h1><p>One conversation across the enterprise. Every grounded answer keeps its evidence attached.</p></div>
        <div className="workspace-advisor"><div><b>Evidence mode</b><span>{health?.llm === "groq" ? "LLM + validator" : "Deterministic verified"} · sources stay attached</span></div></div>
      </div>

      <section className="workspace-shell">
        <div className="chat-toolbar">
          <div className="toolbar-left"><div className="toolbar-label"><Funnel size={15} /> Route</div>
            <div className="select-wrap"><select value={department} onChange={(event) => setDepartment(event.target.value)} aria-label="Department">
              {departments.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
            </select><CaretDown size={14} /></div>
          </div>
          <div className="toolbar-note"><span className="live-pip" /> {selectedDepartment} · {health?.documents ?? "—"} sources indexed</div>
        </div>

        <div className="chat-log" ref={logRef}>
          {messages.length === 0 && <div className="empty-chat">
            <MagicCard className="welcome-card"><div className="welcome-card__inner"><div className="welcome-icon"><BookOpenText size={22} weight="duotone" /></div><div><div className="welcome-title">What should CHANAKYA investigate?</div><div className="welcome-copy">Ask naturally. I’ll route the question, retrieve the evidence and attach the source.</div></div></div></MagicCard>
            {showSuggestions && <div className="suggestion-grid">{suggestions.map((item, index) => <button key={item} className="suggestion" onClick={() => ask(item)} style={{ "--delay": (index * 35) + "ms" }}><span>{item}</span><ArrowUp size={15} /></button>)}</div>}
          </div>}

          {messages.map((message, index) => <Message key={message.id ?? index} message={message} onSource={onSource} />)}
          {loading && <div className="message-row assistant-row"><div className="assistant-avatar"><Sparkle size={14} weight="fill" /></div><div className="typing-card"><span /><span /><span /></div></div>}
        </div>

        <form className="composer" onSubmit={(event) => { event.preventDefault(); ask(); }}>
          <div className="composer__icon"><MagnifyingGlass size={19} /></div>
          <textarea ref={inputRef} rows={1} value={question} onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(); } }}
            placeholder="Ask about revenue, policies, production, SLAs, people or performance..." maxLength={1000} aria-label="Ask CHANAKYA" />
          <button className="send-button" disabled={!question.trim() || loading}><ArrowUp size={19} weight="bold" /></button>
        </form>
        <div className="composer-foot"><span>Enter to send · Shift + Enter for a new line</span><span>Answers are validated against indexed evidence</span></div>
      </section>
    </div>
  );
}

function Message({ message, onSource }) {
  if (message.role === "user") return <div className="message-row user-row"><div className="user-message">{message.content}</div></div>;
  const result = message.result;
  return <div className="message-row assistant-row">
    <div className="assistant-avatar"><Sparkle size={14} weight="fill" /></div>
    <div className="assistant-message-wrap"><div className="assistant-label">CHANAKYA / VERIFIED RESPONSE</div>
      <MagicCard className="answer-card"><div className="answer-card__body">
        {message.content ? <div className="answer-copy">{message.content}</div> : <div className="answer-skeleton"><span /><span /><span /></div>}
        {message.error && <div className="inline-error">{message.error}</div>}
        {result && !message.streaming && <>
          <div className="answer-status">
            <span className={result.grounded ? "grounded" : "warning"}>{result.grounded ? <CheckCircle size={14} weight="fill" /> : <ShieldCheck size={14} />}{result.grounded ? "Grounded" : "Review sources"}</span>
            <span>{result.mode === "llm" ? "LLM verified" : "Evidence mode"}</span>{result.latency_ms ? <span>{result.latency_ms} ms</span> : null}
          </div>
          {result.calculations?.length > 0 && <div className="calculation-strip"><div className="mini-label">Calculation trail</div>{result.calculations.map((item, i) => <div key={i}>{item}</div>)}</div>}
          {result.sources?.length > 0 && <div className="sources-block">
            <div className="section-heading"><span>Retrieved context</span><small>Open any source for the exact indexed chunk</small></div>
            <div className="source-list">{result.sources.map((item) => <button key={item.source_id} className="source-chip" onClick={() => onSource(item)} disabled={!item.chunk_id}>
              <FileText size={15} weight="duotone" /><span className="source-chip__text"><strong>[{item.source_id}] {item.document}</strong><small>Page {item.page}{item.section ? " · " + item.section : ""}</small></span><LinkSimple size={14} />
            </button>)}</div>
          </div>}
        </>}
      </div></MagicCard>
    </div>
  </div>;
}

function KnowledgeView({ docs, department, setDepartment, onOpen }) {
  const filtered = docs.filter((doc) => !department || doc.department === department);
  return <div className="page">
    <div className="page-heading-row"><div><div className="eyebrow"><Stack size={14} /> Evidence repository</div><h1>Knowledge base</h1><p>Browse the indexed enterprise corpus and open documents at their source page.</p></div>
      <div className="select-wrap"><select value={department} onChange={(e) => setDepartment(e.target.value)}><option value="">All departments</option>{departments.slice(1).map((d) => <option key={d.name} value={d.name}>{d.label}</option>)}</select><CaretDown size={14} /></div>
    </div>
    <div className="knowledge-summary"><MetricCard icon={FileText} label="Indexed documents" value={docs.length} detail="Source-of-truth corpus" /><MetricCard icon={Database} label="Departments" value={new Set(docs.map((d) => d.department)).size} detail="Governed routing scopes" /><MetricCard icon={ShieldCheck} label="Provenance" value="PAGE" detail="Page-level source metadata" /></div>
    <section className="document-grid">{filtered.map((doc) => <MagicCard className="document-card" key={doc.document_id}>
      <div className="document-card-top"><span className="file-badge"><FileText size={17} /></span><span className="doc-type">{doc.content_type || "document"}</span></div>
      <h3 title={doc.name}>{doc.name}</h3><div className="document-meta"><span>{doc.department.replace("_", " ")}</span><span>{doc.chunks ?? "—"} chunks</span></div>
      <button className="document-open" onClick={() => onOpen(doc, 1)}><BookOpenText size={15} /> Inspect document</button>
    </MagicCard>)}</section>
    {filtered.length === 0 && <div className="empty-state">No documents match this department.</div>}
  </div>;
}

function MetricCard({ icon: Icon, label, value, suffix = "", detail }) {
  return <MagicCard className="metric-card"><div className="metric-icon"><Icon size={18} /></div><div><span>{label}</span><strong>{value}{suffix}</strong><small>{detail}</small></div></MagicCard>;
}
function TechRow({ icon: Icon, name, meta }) { return <div className="tech-row"><div className="tech-icon"><Icon size={17} /></div><div><b>{name}</b><span>{meta}</span></div></div>; }
function RuntimeRow({ label, value, ok }) { return <div className="runtime-row"><span>{label}</span><b>{value}</b><i className={ok ? "ok" : ""} /></div>; }

function SourceDrawer({ source, loading, onClose, onOpenDocument }) {
  return <div className="source-overlay" role="presentation" onMouseDown={onClose}>
    <aside className="source-drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
      <div className="source-drawer__header"><div><div className="eyebrow"><LinkSimple size={14} /> Retrieved evidence</div><h2>{loading ? "Opening evidence…" : source.document || "Source"}</h2></div><button className="close-button" onClick={onClose}><X size={19} /></button></div>
      {loading ? <div className="source-loading"><CircleNotch className="spin" size={22} /> Loading exact context</div> : source.error ? <div className="inline-error">{source.error}</div> :
        <div className="source-content">
          <div className="source-meta-grid"><div><span>Department</span><strong>{source.department}</strong></div><div><span>Page</span><strong>{source.page_start === source.page_end ? source.page_start : source.page_start + "–" + source.page_end}</strong></div><div><span>Section</span><strong>{source.section || "N/A"}</strong></div><div><span>Type</span><strong>{source.content_type}</strong></div></div>
          <div className="source-actions"><button className="document-link" onClick={onOpenDocument}><BookOpenText size={16} /> Open source at page {source.page_start || 1}</button><button className="document-link document-link--secondary" onClick={onClose}><X size={15} /> Close</button></div>
          <div className="source-highlight"><div className="micro-label">EXACT INDEXED CHUNK</div><p>{source.text}</p></div>
          <div className="source-note"><ShieldCheck size={15} /> This is the exact chunk CHANAKYA retrieved for the answer. Page navigation is preserved in the document viewer.</div>
        </div>}
    </aside>
  </div>;
}

export default App;
