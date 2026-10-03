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
