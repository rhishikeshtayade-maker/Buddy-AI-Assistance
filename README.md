# BUDDY — Advanced Secure AI Desktop Voice Assistant

[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-blue.svg)](https://microsoft.com)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-brightgreen.svg)](https://python.org)
[![Security](https://img.shields.io/badge/security-AES--256--GCM%20%7C%20Zero--Trust-red.svg)](#security-architecture)

> **“BUDDY — Your Voice. Your Laptop. Your Control.”**

BUDDY is a voice-first, agentic, local-first, modular, and secure desktop AI assistant for Windows. It is engineered to reason, plan multi-step workflows, interact with your computer via sandboxed tools, understand screens securely, and strictly protect sensitive operations through encryption, permissions, and audit logging.

---

## Core Philosophy

- **Voice-first**: Fluid voice activation, speech recognition, and low-latency speech synthesis.
- **Agentic**: Multi-step decomposition, planning, execution, and verification.
- **Local-first**: Capable of offline operations for basic system control, memory, and security.
- **Zero Arbitrary Execution**: The AI cannot run raw shell scripts; only validated, risk-categorized tools are accessible.
- **Strict Cryptography**: AES-256-GCM encryption for private memories and secrets; OS Keyring integration.

---

## Development Status & Loop Roadmap

BUDDY is developed using strict **Loop Engineering**:

- [x] **LOOP 0**: Project Foundation & Architecture Blueprint
- [x] **LOOP 1**: BUDDY Core (Lifecycle, State Machine, Event Bus, Config, Registry, Health, Logging)
- [x] **LOOP 2**: Voice Pipeline (Audio capture, VAD, Wake Word, STT/TTS abstractions)
- [x] **LOOP 3**: AI Provider Layer & Conversational Brain (Unified AIProvider, streaming, retries, Conversation Manager)
- [x] **LOOP 4**: Secure Tool System & Computer Control (Permission Engine, Risk 0-4, Confirmation tokens, PathPolicy, Allowlisted Apps, Sandboxed Filesystem, Empirical Verification)
- [x] **LOOP 5**: Screen Understanding + Controlled Computer Vision (Bounding boxes, VisionTarget, ScreenManager state fingerprinting)
- [x] **LOOP 6**: Controlled Mouse & Keyboard Interaction (Target-bound clicks, keyboard allowlist, stale-screen protection, sensitive text defense, zero coordinate injection)
- [x] **LOOP 7**: Advanced Agentic Task Planning + Multi-Step Execution (Restricted prompt planner, DAG dependency validator, bounded retries, adaptive re-planning, per-step confirmation/auth gating, anti-runaway boundaries)
- [x] **LOOP 8**: Long-Term Memory + Contextual Personalization (Bounded categories: Session, Semantic, Episodic, Profile; conservative secret rejection; prompt injection defense; SQLite backend; Fernet encryption; conflict resolution)
- [x] **LOOP 9**: Advanced Browser Automation + Web Interaction (Playwright integration, isolated clean context, SSRF/URL policy, DOM/accessibility inspection, confidence-scored element identification, prompt injection defense, credential/payment field protection, downloads/uploads security with PathPolicy, bounded wait & upload tools, key allowlist, cancellation support, empirical state verification)
- [x] **LOOP 10**: Contextual Awareness + Proactive Assistance (Coarse activity states, foreground app/window title detection, untrusted notification & calendar providers, contextual scheduler, deterministic relevance scoring, quiet hours & interruption budgets, deduplication, sensitive context suppression, prompt injection defenses, zero-surveillance design: BUDDY does not continuously monitor the user)
- [ ] **LOOP 11**: Encrypted Storage (AES-256-GCM Vault)
- [ ] **LOOP 12**: Credential Management (OS Keyring integration)
- [ ] **LOOP 13**: Security & Permission Engine (Risk Levels 0-4)
- [ ] **LOOP 14**: User Confirmation Workflows
- [ ] **LOOP 15**: Authentication (PIN / Local verification)
- [ ] **LOOP 16**: Tamper-Evident Audit Logging
- [ ] **LOOP 17**: Computer Vision & Screen Understanding
- [ ] **LOOP 18**: Developer Mode (Diagnostic & build tools)
- [ ] **LOOP 19**: Automation Engine (Scheduled & event-driven triggers)
- [ ] **LOOP 20**: Desktop UI (PySide6 Dark-Mode Modern Dashboard)
- [ ] **LOOP 21**: Voice UX (Reactive states & visualizers)
- [ ] **LOOP 22**: Error Recovery & Graceful Degradation
- [ ] **LOOP 23**: Offline Capability & Fallbacks
- [ ] **LOOP 24**: Performance Optimization & Benchmarking
- [ ] **LOOP 25**: Privacy Model & Data Redaction
- [ ] **LOOP 26**: Automated Test Suite (Unit, Integration, Security, E2E)
- [ ] **LOOP 27**: Prompt Injection Defenses
- [ ] **LOOP 28**: Secret Leak Prevention & Scrubbing
- [ ] **LOOP 29**: Version Control & Release Hygiene
- [ ] **LOOP 30**: Final Quality Audit & Production Hardening

---

## Getting Started

Refer to [docs/development.md](file:///d:/BUDDY/docs/development.md) for complete installation, setup, and testing instructions.
