# Agentic AI NOC Incident Resolution Prototype

A local prototype demonstrating an agentic AI approach to telecom Network Operations Center (NOC) incident investigation.

The project explores how an AI agent can use an LLM, NOC diagnostic tools, and structured data models to investigate a network incident and produce an evidence-based assessment.

> **Status:** Phase 1 — Agentic Investigation Foundation

## Purpose

The prototype is being developed as a practical exploration of Agentic AI for telecom operations.

Current goals include:

- LLM-driven incident investigation
- Tool calling
- Simulated telecom NOC diagnostic tools
- Evidence gathering
- Structured incident assessment
- LangGraph-based orchestration
- Local LLM execution
- Automated testing

Autonomous network remediation is intentionally outside the current Phase 1 scope.

## Current Architecture

```text
Incident
   |
   v
NOC AI Agent
   |
   v
LLM
   |
   +----------------+----------------+----------------+
   |                |                |
   v                v                v
Telemetry         Alarms        Network Path
   |                |                |
   +----------------+----------------+
                    |
                    v
             Investigation
                Evidence
                    |
                    v
          Incident Assessment
```

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application development |
| LangGraph | Agent orchestration |
| LangChain | LLM and tool integration |
| Ollama | Local LLM runtime |
| Qwen 3 8B | Local development model |
| Pydantic | Structured data contracts |
| Pytest | Automated testing |

## Project Structure

```text
app/
├── agents/        # Agent components
├── models/        # Structured data models
├── prompts/       # System and incident prompts
├── tools/         # NOC diagnostic tools
├── config.py      # Configuration
├── graph.py       # LangGraph orchestration
├── llm.py         # LLM configuration
├── main.py        # Application entry point
└── state.py       # Agent state

data/
├── incidents.json
├── network/
└── runbooks/

tests/             # Automated tests
```

## Prerequisites

- Python 3.11+
- Ollama
- Qwen 3 8B
- Git

The current development environment is local macOS.

## Setup

Clone the repository and enter the project directory:

```bash
git clone <repository-url>
cd agentic-noc
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Install the local model:

```bash
ollama pull qwen3:8b
```

## Running Tests

Use the project environment's Python interpreter:

```bash
python -m pytest
```

The Phase 1 suite covers incident/model validation, NOC tools, agent execution, and structured assessment.

## Running the Application

```bash
python -m app.main
```

The current entry point initializes the NOC system. The primary investigation flow is exercised through the automated agent tests.

## Design Principles

**Evidence before inference** — obtain factual network information before forming conclusions.

**Recommendation is not authorization** — an AI recommendation should not automatically authorize a network change.

**Structured outputs** — use typed contracts for operational information.

**Provider abstraction** — keep LLM provider/model configuration separate from agent logic.

**Human oversight** — potentially disruptive actions should require appropriate approval.

## Roadmap

### Phase 1 — Agentic Investigation Foundation
- [x] Local development environment
- [x] NOC diagnostic tools
- [x] Local LLM integration
- [x] LangGraph orchestration
- [x] Tool calling
- [x] System/incident prompt separation
- [x] Structured assessment model
- [x] Automated tests

### Phase 2 — Evidence & Assessment
- [ ] Structured LLM assessment
- [ ] Evidence correlation
- [ ] Root-cause classification
- [ ] Confidence and evidence scoring

### Phase 3 — Controlled Remediation
- [ ] Remediation recommendations
- [ ] Risk/policy evaluation
- [ ] Human approval workflow
- [ ] Remediation simulation

### Future
- NOC dashboard
- OSS/NMS and ITSM integration patterns
- Event-driven architecture
- Observability and auditability
- Enterprise security and governance

## Disclaimer

This is a learning and demonstration prototype. Network data and NOC tools are simulated and do not represent a production telecom network. The system does not control real network infrastructure.
