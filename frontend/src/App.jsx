import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpenText,
  CaretDown,
  CheckCircle,
  CircleNotch,
  FileArrowUp,
  FileText,
  Funnel,
  LinkSimple,
  MagnifyingGlass,
  Paperclip,
  Plus,
  ShieldCheck,
  Sparkle,
  X,
} from "@phosphor-icons/react";
import { ChanakyaOrb } from "./components/ChanakyaOrb";
import { MagicCard } from "./components/MagicCard";

const API = import.meta.env.VITE_API_URL || "";

const suggestions = [
  "What was revenue in FY2025 and how much did it grow from FY2024?",
  "What was employee attrition in FY2025 compared with FY2024?",
  "Which production line had the highest defect rate?",
  "What is the SLA for Priority-1 incidents?",
  "Did increased production volume coincide with higher defect rates in Q2?",
  "Calculate the percentage increase in EBITDA between FY2024 and FY2025.",
];

const departmentMeta = {
  "": { label: "All departments", tone: "neutral" },
  finance: { label: "Finance", tone: "finance" },
  hr: { label: "Human Resources", tone: "hr" },
  manufacturing: { label: "Manufacturing", tone: "manufacturing" },
  customer_support: { label: "Customer Support", tone: "support" },
};

function escapeForText(value) {
  return String(value ?? "");
}

function App() {
  const [departments, setDepartments] = useState([]);
  const [department, setDepartment] = useState("");
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState(null);
  const [source, setSource] = useState(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [documentUrl, setDocumentUrl] = useState("");
  const [error, setError] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(true);
  const inputRef = useRef(null);
  const logRef = useRef(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API}/departments`).then((r) => r.json()),
      fetch(`${API}/health`).then((r) => r.json()),
    ])
      .then(([ds, h]) => {
        setDepartments(ds);
        setHealth(h);
      })
      .catch(() => setError("Could not reach the CHANAKYA backend. Make sure port 8000 is running."));
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const departmentLabel = useMemo(
    () => departmentMeta[department]?.label || "All departments",
    [department]
  );

  const ask = async (preset) => {
    const q = (preset ?? question).trim();
    if (!q || loading) return;

    setQuestion("");
    setError("");
    setShowSuggestions(false);
    setMessages((current) => [...current, { role: "user", content: q }]);
    setLoading(true);

    const assistantIndex = messages.length + 1;
    setMessages((current) => [...current, {
      role: "assistant",
      content: "",
      streaming: true,
      id: assistantIndex,
    }]);

    try {
      const response = await fetch(`${API}/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          department: department || null,
        }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.error?.message || `Request failed (${response.status})`);
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

        while (buffer.includes("\n\n")) {
          const index = buffer.indexOf("\n\n");
          const event = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const type = event.match(/event: (\w+)/)?.[1];
          const data = event.match(/data: (.*)/s)?.[1];
          if (!type || data == null) continue;
          const parsed = JSON.parse(data);

          if (type === "token") {
            answer += parsed;
            setMessages((current) =>
              current.map((message, i) =>
                i === assistantIndex
                  ? { ...message, content: answer }
                  : message
              )
            );
          }

          if (type === "done") {
            finalResult = parsed;
          }
        }
      }

      setMessages((current) =>
        current.map((message, i) =>
          i === assistantIndex
            ? {
                ...message,
                content: finalResult?.answer || answer,
                result: finalResult,
                streaming: false,
              }
            : message
        )
      );
    } catch (err) {
      setMessages((current) =>
        current.map((message, i) =>
          i === assistantIndex
            ? {
                ...message,
                content: "I couldn't complete that request.",
                streaming: false,
                error: err.message,
              }
            : message
        )
      );
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 40);
    }
  };

  const openSource = async (item) => {
    if (!item?.chunk_id) return;
    setSourceLoading(true);
    setSource(null);
    try {
      const response = await fetch(`${API}/sources/${item.chunk_id}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || "Source unavailable");
      setSource(payload);
      const page = payload.page_start || 1;
      setDocumentUrl(payload.document_id ? `${API}/documents/${payload.document_id}/file#page=${page}` : "");
    } catch (err) {
      setSource({ error: err.message });
      setDocumentUrl("");
    } finally {
      setSourceLoading(false);
    }
  };

  const newConversation = () => {
    setMessages([]);
    setShowSuggestions(true);
    setError("");
    inputRef.current?.focus();
  };

  return (
    <div className="app-shell">
      <div className="paper-grid" aria-hidden="true" />

      <header className="topbar">
        <div className="topbar__brand">
          <div className="brand-mark"><Sparkle weight="fill" size={14} /></div>
          <div>
            <div className="brand-name">CHANAKYA</div>
            <div className="brand-kicker">Enterprise intelligence</div>
          </div>
        </div>

        <div className="topbar__status">
          <span className={`status-dot ${health?.status === "ok" ? "is-online" : ""}`} />
          <span>{health?.status === "ok" ? "Knowledge online" : "Connecting"}</span>
          <span className="topbar__divider" />
          <span>{health?.documents ?? "—"} documents</span>
          <span className="topbar__divider" />
          <span>{health?.chunks ?? "—"} chunks</span>
        </div>

        <button className="new-chat-button" onClick={newConversation}>
          <Plus size={17} weight="bold" />
          <span>New chat</span>
        </button>
      </header>

      <main className="workspace">
        <section className="hero-row">
          <div className="hero-copy">
            <div className="eyebrow"><ShieldCheck size={15} weight="bold" /> Evidence-first enterprise knowledge</div>
            <h1>Ask the business.<br /><span>Get the evidence.</span></h1>
            <p>
              One governed conversation across Finance, HR, Manufacturing and Customer Support.
              CHANAKYA routes the question, retrieves the right context and shows you exactly where it came from.
            </p>
            <div className="hero-meta">
              <span><CheckCircle size={15} weight="fill" /> Grounded answers</span>
              <span><CheckCircle size={15} weight="fill" /> Numerical reasoning</span>
              <span><CheckCircle size={15} weight="fill" /> Source-linked context</span>
            </div>
          </div>

          <div className="hero-orb-wrap">
            <ChanakyaOrb />
            <div className="orb-caption">
              <span>CHANAKYA</span>
              <small>Wisdom layer active</small>
            </div>
          </div>
        </section>

        <section className="chat-shell">
          <div className="chat-toolbar">
            <div className="toolbar-left">
              <div className="toolbar-label"><Funnel size={15} /> Route</div>
              <div className="select-wrap">
                <select value={department} onChange={(event) => setDepartment(event.target.value)} aria-label="Department">
                  <option value="">All departments</option>
                  {departments.map((item) => (
                    <option key={item.name} value={item.name}>{item.label}</option>
                  ))}
                </select>
                <CaretDown size={14} />
              </div>
            </div>
            <div className="toolbar-note">
              <span className="live-pip" />
              {departmentLabel} · {health?.llm === "groq" ? "Groq reasoning" : "Offline verified mode"}
            </div>
          </div>

          <div className="chat-log" ref={logRef}>
            {messages.length === 0 && (
              <div className="empty-chat">
                <MagicCard className="welcome-card">
                  <div className="welcome-card__inner">
                    <div className="welcome-icon"><BookOpenText size={22} weight="duotone" /></div>
                    <div>
                      <div className="welcome-title">What should CHANAKYA investigate?</div>
                      <div className="welcome-copy">
                        Ask naturally. Department routing is automatic, and retrieved evidence stays attached to the answer.
                      </div>
                    </div>
                  </div>
                </MagicCard>

                {showSuggestions && (
                  <div className="suggestion-grid">
                    {suggestions.map((item, index) => (
                      <button
                        key={item}
                        className="suggestion"
                        onClick={() => ask(item)}
                        style={{ "--delay": `${index * 35}ms` }}
                      >
                        <span>{item}</span>
                        <ArrowUp size={15} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {messages.map((message, index) => (
              <Message
                key={message.id ?? index}
                message={message}
                onSource={openSource}
              />
            ))}

            {loading && (
              <div className="message-row assistant-row">
                <div className="assistant-avatar"><Sparkle size={14} weight="fill" /></div>
                <div className="typing-card" aria-label="CHANAKYA is thinking">
                  <span /><span /><span />
                </div>
              </div>
            )}
          </div>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              ask();
            }}
          >
            <div className="composer__icon"><MagnifyingGlass size={19} /></div>
            <textarea
              ref={inputRef}
              rows={1}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  ask();
                }
              }}
              placeholder="Ask CHANAKYA anything about the enterprise..."
              maxLength={1000}
              aria-label="Ask CHANAKYA"
            />
            <div className="composer__actions">
              <button type="button" className="icon-button" title="Upload documents is available in the backend" disabled>
                <Paperclip size={18} />
              </button>
              <button className="send-button" disabled={!question.trim() || loading} aria-label="Send">
                <ArrowUp size={19} weight="bold" />
              </button>
            </div>
          </form>

          <div className="composer-foot">
            <span>Enter to send · Shift + Enter for a new line</span>
            <span>Responses are grounded against the indexed knowledge base</span>
          </div>
        </section>

        {error && <div className="global-error"><X size={16} /> {error}</div>}
      </main>

      {source && (
        <SourceDrawer source={source} loading={sourceLoading} onClose={() => { setSource(null); setDocumentUrl(""); }} />
      )}
    </div>
  );
}

function Message({ message, onSource }) {
  if (message.role === "user") {
    return (
      <div className="message-row user-row">
        <div className="user-message">{message.content}</div>
      </div>
    );
  }

  const result = message.result;
  return (
    <div className="message-row assistant-row">
      <div className="assistant-avatar"><Sparkle size={14} weight="fill" /></div>
      <div className="assistant-message-wrap">
        <div className="assistant-label">CHANAKYA</div>
        <MagicCard className="answer-card">
          <div className="answer-card__body">
            {message.content ? (
              <div className="answer-copy">{message.content}</div>
            ) : (
              <div className="answer-skeleton"><span /><span /><span /></div>
            )}

            {message.error && <div className="inline-error">{message.error}</div>}

            {result && !message.streaming && (
              <>
                <div className="answer-status">
                  <span className={result.grounded ? "grounded" : "warning"}>
                    {result.grounded ? <CheckCircle size={14} weight="fill" /> : <ShieldCheck size={14} />}
                    {result.grounded ? "Grounded" : "Review sources"}
                  </span>
                  <span>{result.mode === "llm" ? "LLM verified" : "Evidence mode"}</span>
                  {result.latency_ms ? <span>{result.latency_ms} ms</span> : null}
                </div>

                {result.calculations?.length > 0 && (
                  <div className="calculation-strip">
                    <div className="mini-label">Calculation</div>
                    {result.calculations.map((item, i) => <div key={i}>{item}</div>)}
                  </div>
                )}

                {result.sources?.length > 0 && (
                  <div className="sources-block">
                    <div className="section-heading"><span>Retrieved context</span><small>Click a source to inspect the exact chunk</small></div>
                    <div className="source-list">
                      {result.sources.map((item) => (
                        <button
                          key={item.source_id}
                          className="source-chip"
                          onClick={() => onSource(item)}
                          disabled={!item.chunk_id}
                          title={item.chunk_id ? "Open exact retrieved context" : "Source metadata unavailable"}
                        >
                          <FileText size={15} weight="duotone" />
                          <span className="source-chip__text">
                            <strong>[{item.source_id}] {item.document}</strong>
                            <small>Page {item.page}{item.section ? ` · ${item.section}` : ""}</small>
                          </span>
                          <LinkSimple size={14} />
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {result.evidence?.length > 0 && (
                  <details className="evidence-details">
                    <summary>Evidence snippets <span>{result.evidence.length}</span></summary>
                    <div className="evidence-stack">
                      {result.evidence.map((item) => (
                        <div className="evidence-item" key={item.source_id}>
                          <div className="evidence-item__top">
                            <span>[{item.source_id}] {item.document}</span>
                            <span>p. {item.page}</span>
                          </div>
                          <p>{item.text}</p>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </>
            )}
          </div>
        </MagicCard>
      </div>
    </div>
  );
}

function SourceDrawer({ source, loading, onClose }) {
  return (
    <div className="source-overlay" role="presentation" onMouseDown={onClose}>
      <aside className="source-drawer" role="dialog" aria-modal="true" aria-label="Retrieved source" onMouseDown={(event) => event.stopPropagation()}>
        <div className="source-drawer__header">
          <div>
            <div className="eyebrow"><LinkSimple size={14} /> Retrieved source</div>
            <h2>{loading ? "Opening evidence…" : source.document || "Source"}</h2>
          </div>
          <button className="close-button" onClick={onClose} aria-label="Close source">
            <X size={19} />
          </button>
        </div>

        {loading ? (
          <div className="source-loading"><CircleNotch className="spin" size={22} /> Loading exact context</div>
        ) : source.error ? (
          <div className="inline-error">{source.error}</div>
        ) : (
          <div className="source-content">
            <div className="source-meta-grid">
              <div><span>Department</span><strong>{source.department}</strong></div>
              <div><span>Page</span><strong>{source.page_start === source.page_end ? source.page_start : `${source.page_start}–${source.page_end}`}</strong></div>
              <div><span>Section</span><strong>{source.section || "N/A"}</strong></div>
              <div><span>Type</span><strong>{source.content_type}</strong></div>
            </div>
            <div className="source-actions">
              {documentUrl && source.document?.toLowerCase().endsWith(".pdf") && (
                <a className="document-link" href={documentUrl} target="_blank" rel="noreferrer">
                  <BookOpenText size={16} />
                  Open document at page {source.page_start}
                </a>
              )}
              <button className="document-link document-link--secondary" onClick={onClose}>
                <X size={15} />
                Close source
              </button>
            </div>
            <div className="source-highlight">
              <div className="mini-label">Exact retrieved context</div>
              <p>{source.text}</p>
            </div>
            <div className="source-note">
              <BookOpenText size={17} />
              This view is the exact indexed chunk used by CHANAKYA, preserving its document name, page and section provenance.
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

export default App;
