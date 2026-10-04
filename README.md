# CHANAKYA
## Agentic Enterprise Knowledge & Business Automation Platform

> **Enterprise intelligence, grounded in evidence.**

CHANAKYA is a production-oriented Agentic RAG platform designed to answer enterprise business questions across **Finance, HR, Manufacturing and Customer Support**.

Instead of treating enterprise RAG as a simple document chatbot, CHANAKYA separates:

- Query routing
- Hybrid retrieval
- Evidence sufficiency
- Table reasoning
- Numerical reasoning
- LLM answer generation
- Citation validation
- Hallucination/refusal handling

The system is designed around one principle:

> **If the knowledge base does not provide sufficient evidence, CHANAKYA should not invent an answer.**

---

# 1. Project Overview

CHANAKYA was developed for the course:

**Agentic AI for Business Automation**

**Faculty:** Professor Ashok Harnal

### Team

| Member | ID | Responsibility |
|---|---:|---|
| Parv Jhamb | 065040 | Backend, retrieval, embeddings, orchestration, Supabase, evaluation |
| Awantika Kholia | 065060 | Knowledge base, datasets, evaluation questions |
| Aman Malhi | 065010 | Frontend, deployment and product interface |

---

# 2. Business Problem

Large organizations store critical knowledge across:

- Annual reports
- Financial policies
- Budgets
- HR manuals
- Employee handbooks
- Manufacturing reports
- Production records
- Maintenance reports
- Quality manuals
- Customer-support manuals
- SLA handbooks
- Ticket registers
- Excel workbooks
- CSV operational datasets

Traditional keyword search forces employees to manually locate information.

Generic LLM chatbots create a different problem:

> They may generate plausible answers that are not actually supported by enterprise evidence.

CHANAKYA addresses both problems.

It provides a governed question-answering layer capable of retrieving enterprise evidence, reasoning over structured data, performing calculations and validating generated answers before returning them.

---

# 3. Core Capabilities

## Enterprise RAG

- Document ingestion
- Structure-aware chunking
- Page-level provenance
- Section metadata
- Table preservation
- Document/version tracking
- Department classification

## Hybrid Retrieval

CHANAKYA combines:

- Dense vector retrieval
- PostgreSQL full-text search
- Keyword retrieval
- Reciprocal Rank Fusion
- Relevance filtering
- Evidence sufficiency checks

## Numerical Intelligence

The numerical layer can:

- Identify numerical facts
- Normalize quantities
- Compare periods
- Calculate percentage change
- Calculate differences
- Handle percentage-point changes
- Produce calculation formulas
- Validate calculated values against evidence

## Table Intelligence

The system supports:

- Table lookup
- Row matching
- Column matching
- Priority/SLA lookup
- Multi-document table reasoning
- Structured numerical evidence

## Grounded Generation

LLM responses are validated before being displayed.

The validator checks:

- Citation validity
- Source existence
- Numeric grounding
- Unsupported figures
- Fabricated citations
- Evidence coverage

If validation fails, CHANAKYA falls back to a deterministic evidence-based answer.

## Refusal

When evidence is insufficient, the system explicitly refuses instead of hallucinating.

---

# 4. Supported Departments

### Finance

Examples:

- Revenue
- Profit
- Budgets
- Forecasts
- Financial controls
- Cost centers
- Annual reports

### Human Resources

Examples:

- Leave policies
- Compensation
- Performance management
- Employee handbook
- HR policies

### Manufacturing

Examples:

- Production
- Machine downtime
- Maintenance
- Quality
- Safety
- Production targets

### Customer Support

Examples:

- Support tickets
- SLA targets
- Escalation policies
- First-response targets
- Resolution targets
- Product support

---

# 5. System Architecture

```mermaid
flowchart TD

    U[User] --> UI[Streamlit Enterprise UI]

    UI --> APP[CHANAKYA App]

    APP --> ORCH[Agentic Query Orchestrator]

    ORCH --> ROUTER[Query Router]

    ROUTER --> QT[Question Type Detection]
    ROUTER --> DEPT[Department Routing]

    QT --> RET[Hybrid Retrieval]
    DEPT --> RET

    RET --> VEC[Dense Vector Retrieval]
    RET --> FTS[PostgreSQL Full Text / Keyword Retrieval]

    VEC --> FUSION[Rank Fusion / RRF]
    FTS --> FUSION

    FUSION --> RERANK[Relevance / IDF Reranking]
    RERANK --> GATE[Evidence Sufficiency Gate]

    GATE -->|Insufficient Evidence| REFUSE[Grounded Refusal]
    GATE -->|Sufficient Evidence| REASON[Reasoning Layer]

    REASON --> TABLE[Table Intelligence]
    REASON --> NUM[Numerical Engine]

    TABLE --> CONTEXT[Evidence Context]
    NUM --> CONTEXT

    CONTEXT --> LLM[GPT-OSS 120B via Groq]

    LLM --> VALIDATE[Citation & Grounding Validator]

    VALIDATE -->|Valid| ANSWER[Verified Answer]
    VALIDATE -->|Invalid| FALLBACK[Deterministic Evidence Answer]

    ANSWER --> UI
    FALLBACK --> UI
    REFUSE --> UI

    DB[(Supabase PostgreSQL)]
    PGV[(pgvector)]
    STORAGE[(Supabase Storage)]

    DB --> FTS
    PGV --> VEC
    STORAGE --> DB

    RET -.-> DB
    RET -.-> PGV
