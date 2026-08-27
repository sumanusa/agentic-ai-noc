# Architecture

## 1. Overview

The Agentic AI NOC Incident Resolution Prototype demonstrates an agentic workflow for investigating simulated telecom network incidents.

The current implementation focuses on **investigation**, not autonomous remediation.

Key architectural elements are:

- LLM reasoning and tool selection
- LangGraph orchestration
- Read-only NOC diagnostic tools
- Structured data models
- Separate system and incident prompts
- Automated tests

## 2. Current Architecture

```text
                         Incident
                            |
                            v
                  +-------------------+
                  |   LangGraph Agent |
                  |                   |
                  | Investigation     |
                  +---------+---------+
                            |
                            v
                     +-------------+
                     |     LLM     |
                     |  Qwen 3 8B  |
                     +------+------+ 
                            |
                     Tool selection
                            |
          +-----------------+-----------------+
          |                 |                 |
          v                 v                 v
      Telemetry          Alarms          Network Path
          |                 |                 |
          +-----------------+-----------------+
                            |
                            v
                   Investigation Evidence
                            |
                            v
                    Incident Assessment
```

## 3. Incident Input

An incident provides context for the investigation, such as:

- Site identifier
- Incident description
- Customer-impact symptoms

Incident-specific information is kept separate from generic agent behavior so the same workflow can investigate different incidents.

## 4. Prompt Separation

The project separates:

**System prompt** — defines generic NOC agent behavior and investigation principles.

**Incident context** — provides the specific site and incident information.

Conceptually:

```text
Generic Agent Behavior
        +
Incident Context
        +
Available Tools
        |
        v
    Investigation
```

This avoids embedding a particular incident into the core agent behavior.

## 5. LLM Layer

The application accesses the LLM through a dedicated configuration layer.

The current local development environment uses:

- Ollama
- Qwen 3 8B

The model/provider configuration is kept separate from the core agent logic so the architecture can evolve toward other model providers or deployment environments.

## 6. NOC Tool Layer

The agent currently has access to simulated, read-only diagnostic tools.

### Telemetry

Provides information such as:

- Packet loss
- Latency
- CPU utilization
- Active users

### Alarms

Provides active alarms associated with a site.

### Network Path

Provides information such as:

- Backhaul
- Router
- Interface

The tools provide factual operational data. They do not make the diagnosis themselves.

```text
Agent
  |
  | requests information
  v
NOC Tool
  |
  | returns factual data
  v
Agent
  |
  | reasons over evidence
  v
Assessment
```

## 7. Agent Orchestration

LangGraph manages the investigation workflow.

The conceptual flow is:

```text
Incident
   |
   v
Agent reasoning
   |
   v
Tool invocation
   |
   v
Tool result
   |
   v
Further reasoning
   |
   v
Assessment
```

This differs from a simple single-turn LLM request because the agent can determine what information it needs and invoke tools during the investigation.

## 8. Structured Assessment

The project defines an `IncidentAssessment` Pydantic model as a typed contract for incident assessment.

The model includes fields such as:

- Incident ID
- Site
- Root cause
- Evidence
- Confidence
- Recommended action
- Risk
- Human approval requirement

The model is currently defined and tested. Integration of structured LLM-generated assessment is part of the next development stage.

## 9. Evidence Before Inference

The intended reasoning pattern is:

```text
Incident Symptoms
       |
       v
Gather Evidence
       |
       v
Correlate Evidence
       |
       v
Determine Likely Cause
       |
       v
Assess Confidence
       |
       v
Recommend Next Action
```

The agent should use available diagnostic evidence rather than inventing network facts.

## 10. Separation of Recommendation and Authorization

A central design principle is that an AI recommendation should not automatically authorize a network change.

The intended future flow is:

```text
Investigation
     |
     v
Assessment
     |
     v
Recommendation
     |
     v
Policy / Risk Evaluation
     |
     +----> Approval required
     |
     +----> Approved action
```

High-impact remediation should be subject to appropriate policy and/or human approval.

## 11. Data

The prototype uses simulated data for:

- Incidents
- Network sites
- Telemetry
- Alarms
- Network paths
- Example runbooks

This permits development without access to production telecom systems.

## 12. Testing

The project uses Pytest for both component and integrated behavior.

Tests currently cover:

- Incident validation
- Assessment model validation
- Telemetry
- Alarms
- Network path information
- Agent execution

The goal is to maintain a stable baseline while the agent architecture evolves.

## 13. Production Direction

A production-oriented implementation could evolve toward:

```text
Telecom Events / OSS / NMS / ITSM
                |
                v
        Incident Integration
                |
                v
        Agent Orchestrator
                |
        +-------+-------+
        |       |       |
        v       v       v
     Tools   Knowledge  Context
        |       |       |
        +-------+-------+
                |
                v
          Evidence Layer
                |
                v
        AI Assessment
                |
                v
       Policy / Guardrails
                |
         +------+------+
         |             |
         v             v
   Human Approval   Approved
                       |
                       v
                  Remediation
```

These production integrations are architectural direction only and are not implemented in the current prototype.

## 14. Architectural Principles

1. **Evidence before inference** — gather operational facts before concluding.
2. **Separate reasoning from execution** — recommendations do not automatically execute changes.
3. **Read before write** — diagnostic capabilities should be separated from state-changing capabilities.
4. **Typed contracts** — use structured models between major components.
5. **Provider abstraction** — avoid coupling agent logic to one LLM provider.
6. **Human oversight** — require appropriate controls for high-risk actions.
7. **Incremental autonomy** — increase autonomy as confidence, controls, and observability mature.
