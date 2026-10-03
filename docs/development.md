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

## 5. Running Tests

```powershell
# Run all unit tests via pytest (includes all automated voice tests)
pytest tests/unit

# Or using standard unittest runner
python -m unittest discover -s tests -v

# Run security test suite
pytest tests/security

# Run integration tests
pytest tests/integration
```
