# Development Guide

## 1. Environment

The project is currently developed locally on macOS using:

- Python 3.11
- Visual Studio Code
- Python virtual environment (`.venv`)
- Ollama
- Qwen 3 8B
- Git

## 2. Clone and Open

```bash
git clone <repository-url>
cd agentic-noc
code .
```

If `code` is not available, open the project folder directly in VS Code.

## 3. Virtual Environment

Create the environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Verify:

```bash
which python
```

It should point to the project's `.venv/bin/python`.

## 4. Dependencies

Install dependencies into the active environment:

```bash
python -m pip install -r requirements.txt
```

Using `python -m pip` helps ensure packages are installed into the same environment used to run the project.

## 5. Pytest

Run tests with:

```bash
python -m pytest
```

Prefer this over a globally installed `pytest` command.

This is particularly important if Conda or another Python installation is also present on the machine.

To verify the environment:

```bash
which python
which pytest
```

`python -m pytest` should still be used even if `which pytest` points somewhere else.

## 6. Ollama

Verify Ollama:

```bash
ollama --version
```

List installed models:

```bash
ollama list
```

Install the current development model if necessary:

```bash
ollama pull qwen3:8b
```

The current implementation uses Ollama locally. Provider/model configuration should remain separate from agent logic.

## 7. Configuration and Secrets

Local environment-specific values may be stored in:

```text
.env
```

Do not commit:

- API keys
- Passwords
- Access tokens
- Credentials
- Private endpoints
- Other sensitive configuration

The `.gitignore` excludes `.env`, `.venv`, Python caches, and pytest caches.

## 8. Run the Application

From the project root:

```bash
python -m app.main
```

The current entry point initializes the Agentic AI NOC system.

## 9. Run Tests

Full suite:

```bash
python -m pytest
```

Verbose output:

```bash
python -m pytest -v
```

Specific test:

```bash
python -m pytest tests/test_agent.py -v
```

## 10. Development Workflow

Use a small, testable change cycle:

```text
Make Change
    |
    v
Run Focused Test
    |
    v
Run Full Test Suite
    |
    v
Review Git Diff
    |
    v
Commit
    |
    v
Push
```

Typical commands:

```bash
python -m pytest
git status
git diff
git add .
git commit -m "Describe the change"
git push
```

## 11. Project Conventions

### Prompts

Keep generic agent behavior in the system prompt.

Keep incident-specific information separate so it can be supplied as input.

### Tools

Tools should provide factual operational information and avoid embedding diagnosis or business logic that belongs in the agent/assessment layer.

### Models

Use Pydantic models for important structured data contracts.

### Tests

Add or update tests when changing tools, models, or agent behavior.

## 12. Current Scope

The current prototype uses simulated network data and read-only NOC tools.

It does not:

- Connect to production telecom infrastructure
- Execute real network changes
- Provide autonomous remediation
- Store production customer data

Future capabilities should be introduced incrementally with appropriate policy, authorization, auditability, and human oversight.
