# BUDDY Loop Engineering & Development Guide

## 1. Loop Engineering Methodology

Every development task follows the disciplined engineering loop:

```
OBSERVE -> UNDERSTAND -> PLAN -> IMPLEMENT -> RUN -> TEST -> VERIFY -> DIAGNOSE -> FIX -> RETEST -> DOCUMENT -> NEXT LOOP
```

### Protocol Rules:
- **Never assume generated code works without execution.**
- **Never commit or push code that fails automated tests.**
- **Run small, reversible, typed increments.**
- **Zero hard-coded secrets or bypasses.**

---

## 2. Environment Setup

### Prerequisites
- Python 3.11+ (Python 3.13 supported)
- Windows 10/11 64-bit
- Git

### Setup Steps
```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Upgrade pip
python -m pip install --upgrade pip

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Copy configuration template
cp .env.example .env
```

---

## 3. Running BUDDY Core Runtime & Diagnostics

```powershell
# Run the core runtime bootstrap and diagnostics
python -m app.main

# Run in persistent event-loop mode
python -m app.main --run
```

---

## 4. Running BUDDY Voice Subsystem & Smoke Test

```powershell
# Run the live hardware voice smoke test (mic + speaker)
python -m app.voice.smoke_test
```

---

## 5. Running BUDDY CLI Chat Mode (Keyboard / Text Testing)

```powershell
# Converse with BUDDY via interactive command-line interface
python -m app.ai.chat
```

---

## 6. Running Tests

```powershell
# Run all unit tests via pytest
pytest tests/unit

# Run security test suite (path traversal, arbitrary execution defense, confirmation forgery)
pytest tests/security

# Run end-to-end tool execution suite
pytest tests/e2e

# Run all tests using standard unittest runner
python -m unittest discover -s tests -v
```

---

## 7. Interactive Tool Execution Testing (CLI Chat)

```powershell
# Test tools and interactive confirmation prompts in CLI chat
python -m app.ai.chat

# Example tool prompts in chat:
# You: Open Notepad
# You: Get battery status
# You: Get system info
```

---

## 8. Controlled Mouse & Keyboard Interaction Testing (Loop 6)

```powershell
# Run the automated interaction smoke test (Notepad launch -> verified click -> text typing -> cleanup)
python -m app.tools.smoke_test_interaction

# Run in headless / mock mode (ideal for CI and isolated testing)
python -m app.tools.smoke_test_interaction --mock

# Run the 19-point adversarial interaction security suite
pytest tests/security/test_interaction_security.py -v

# Run mouse and keyboard unit tests
pytest tests/unit/test_mouse_tools.py tests/unit/test_keyboard_tools.py tests/unit/test_interaction_policy.py -v
```

---

## 9. Agentic Task Planning & Multi-Step Execution Testing (Loop 7)

```powershell
# Run the real Windows multi-step planning smoke test (Notepad open -> focus -> type -> confirm -> finish)
python -m app.agent.smoke_test_agent

# Run in deterministic mock / headless mode (suitable for CI)
python -m app.agent.smoke_test_agent --mock

# Run agent unit tests (models, planner, validator, executor, policies)
pytest tests/unit/test_agent_models.py tests/unit/test_agent_planner.py tests/unit/test_agent_validator.py tests/unit/test_agent_executor.py tests/unit/test_agent_policies.py -v

# Run agent security tests (adversarial plan rejection, risk tampering, forbidden tool blocks)
pytest tests/security/test_agent_security.py -v

# Run agent end-to-end tests (multi-step sequence & partial failure honesty)
pytest tests/e2e/test_agent_e2e.py -v
```

---

## 10. Long-Term Memory & Contextual Personalization Testing (Loop 8)

```powershell
# Run the real Windows memory smoke test (persistence across restart, updates, deletions, secret rejection)
python -m app.memory.smoke_test_memory

# Run memory unit tests (models, store, policy, service, manager, retrieval, conflicts, encryption)
pytest tests/unit/test_memory_models.py tests/unit/test_memory_store.py tests/unit/test_memory_policy.py tests/unit/test_memory_service.py tests/unit/test_memory_manager.py tests/unit/test_memory_retrieval.py tests/unit/test_memory_conflicts.py tests/unit/test_memory_encryption.py -v

# Run the 25-point memory security & privacy test suite (passwords, tokens, JWTs, injection defense, bypass prevention)
pytest tests/security/test_memory_security.py -v

# Run memory end-to-end lifecycle & conversation integration tests
pytest tests/e2e/test_memory_e2e.py -v
```

---

## 11. Browser Automation & Web Interaction Testing (Loop 9)

```powershell
# Run the real Windows browser smoke test (local deterministic test page, click, type, tabs, downloads)
python -m app.browser.smoke_test_browser

# Run all 11 browser unit test suites (models, policy, session, dom, accessibility, actions, downloads, uploads, extraction, verification, limits)
pytest tests/unit/test_browser_models.py tests/unit/test_browser_policy.py tests/unit/test_browser_session.py tests/unit/test_browser_dom.py tests/unit/test_browser_accessibility.py tests/unit/test_browser_actions.py tests/unit/test_browser_downloads.py tests/unit/test_browser_uploads.py tests/unit/test_browser_extraction.py tests/unit/test_browser_verification.py tests/unit/test_browser_limits.py -v

# Run comprehensive browser security tests (SSRF, schemes, prompt injection, credentials, download restrictions)
pytest tests/security/test_browser_security.py -v

# Run browser E2E workflows, adversarial prompt injection containment, and honest failure tests
pytest tests/e2e/test_browser_e2e.py -v
```

