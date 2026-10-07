"""BUDDY Live Voice Command Router.

Provides typed classification of spoken utterances into structured voice intents:
- TOOL_REQUEST: Verified desktop actions (app.open, app.close, system.get_battery, system.get_volume, system.set_volume)
- MEMORY_REMEMBER: Explicit memory storage via MemoryManager / MemoryPolicy
- MEMORY_RECALL: Targeted memory querying
- MEMORY_FORGET: Targeted memory removal
- SECURITY_SENSITIVE: Prohibited or destructive requests (e.g. modifying/deleting system files, arbitrary execution)
- CONVERSATION: Natural language queries, explanations, and conversational turns
- UNKNOWN: Ambiguous utterances routed safely to conversation

NEVER executes arbitrary shell, powershell, cmd, eval, exec, or child process commands.
All computer actions MUST pass through ToolRegistry -> ToolExecutor -> PermissionEngine -> Verification.
"""

from __future__ import annotations

import datetime
from enum import Enum
import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class VoiceIntentType(str, Enum):
    """Categorization of recognized voice intent."""

    TOOL_REQUEST = "tool_request"
    MEMORY_REMEMBER = "memory_remember"
    MEMORY_RECALL = "memory_recall"
    MEMORY_FORGET = "memory_forget"
    SECURITY_SENSITIVE = "security_sensitive"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


class VoiceIntent(BaseModel):
    """Structured, strongly typed representation of parsed voice intent."""

    intent_type: VoiceIntentType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    normalized_text: str
    tool_name: Optional[str] = None
    tool_arguments: Dict[str, Any] = Field(default_factory=dict)
    memory_content: Optional[str] = None
    target: Optional[str] = None
    reason: Optional[str] = None
    refusal_message: Optional[str] = None
    direct_response: Optional[str] = None

    model_config = {
        "extra": "forbid",
    }


# Allowlisted application aliases matching app.open and app.close
APP_ALIASES: Dict[str, str] = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "mspaint": "mspaint",
    "explorer": "explorer",
    "file explorer": "explorer",
}

# Regex patterns for clearly destructive or prohibited security-sensitive requests
SECURITY_SENSITIVE_PATTERNS = [
    r"\b(?:delete|remove|erase|format|wipe)\s+(?:the\s+)?(?:windows|system|c:\\windows|system32|registry|boot)\b",
    r"\b(?:delete|destroy|drop)\s+(?:the\s+)?(?:system\s+files?|windows\s+directory|boot\s+records?)\b",
    r"\b(?:run|execute|launch)\s+(?:powershell|cmd|command\s+prompt|bash|shell|terminal|eval|exec)\b",
    r"\b(?:format\s+c:|rm\s+-rf|del\s+/f|del\s+/s)",
    r"\b(?:disable|bypass|kill)\s+(?:the\s+)?(?:firewall|antivirus|defender|security\s+policy)\b",
    r"\b(?:steal|dump|exfiltrate)\s+(?:passwords?|credentials?|tokens?|keys?)\b",
]


class VoiceCommandRouter:
    """Classifies spoken natural language transcripts into structured VoiceIntent objects."""

    def classify(self, text: str) -> VoiceIntent:
        """Parse raw speech transcript into a structured VoiceIntent."""
        raw = text.strip()
        cleaned = raw.lower().rstrip(".!? ")

        # Strip leading wake words or conversational prefixes if present in transcript
        for prefix in ("hey buddy,", "hey buddy", "ok buddy,", "ok buddy", "buddy,", "buddy"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip(" ,")
                break

        if not cleaned:
            return VoiceIntent(
                intent_type=VoiceIntentType.CONVERSATION,
                normalized_text="",
                confidence=1.0,
            )

        # 1. Check for SECURITY_SENSITIVE / destructive patterns
        for pattern in SECURITY_SENSITIVE_PATTERNS:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return VoiceIntent(
                    intent_type=VoiceIntentType.SECURITY_SENSITIVE,
                    normalized_text=raw,
                    reason="Request targets protected system components or forbidden execution primitives",
                    refusal_message="I cannot perform that request because it targets protected system files or restricted operations.",
                )

        # 2. Check System Info & Tool Requests
        # 2a. Battery Level: "what is my battery level", "battery status", "how much battery"
        if any(p in cleaned for p in ["battery level", "battery status", "how much battery", "check battery", "battery percent", "battery"]):
            if not any(k in cleaned for k in ["save", "buy", "replace", "explain"]):
                return VoiceIntent(
                    intent_type=VoiceIntentType.TOOL_REQUEST,
                    normalized_text=raw,
                    tool_name="system.get_battery",
                    tool_arguments={},
                )

        # 2b. Volume Query: "what is my current volume", "current volume", "get volume"
        if any(p in cleaned for p in ["current volume", "system volume", "get volume", "what is the volume", "what is my volume"]):
            return VoiceIntent(
                intent_type=VoiceIntentType.TOOL_REQUEST,
                normalized_text=raw,
                tool_name="system.get_volume",
                tool_arguments={},
            )

        # 2c. Set Volume: "set volume to 30 percent", "set volume to 50"
        set_vol_match = re.search(r"\b(?:set|change|adjust)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)(?:\s*%)?", cleaned)
        if set_vol_match:
            try:
                level_val = int(set_vol_match.group(1))
                return VoiceIntent(
                    intent_type=VoiceIntentType.TOOL_REQUEST,
                    normalized_text=raw,
                    tool_name="system.set_volume",
                    tool_arguments={"level": level_val},
                )
            except ValueError:
                pass

        # 2d. Open Application: "open Notepad", "launch Calculator", "open Calc"
        open_match = re.search(r"\b(?:open|launch|start)\s+([a-zA-Z0-9_\- ]+)", cleaned)
        if open_match:
            target_app_raw = open_match.group(1).strip()
            for alias, target_name in APP_ALIASES.items():
                if target_app_raw == alias or target_app_raw.startswith(alias):
                    return VoiceIntent(
                        intent_type=VoiceIntentType.TOOL_REQUEST,
                        normalized_text=raw,
                        tool_name="app.open",
                        tool_arguments={"application": target_name},
                        target=target_name,
                    )

        # 2e. Close Application: "close Notepad", "close Notepad on my screen", "exit Calculator"
        close_match = re.search(r"\b(?:close|terminate|exit|quit|stop)\s+([a-zA-Z0-9_\- ]+)", cleaned)
        if close_match:
            target_app_raw = close_match.group(1).strip()
            # If the command is simply "exit" or "quit" without an app, let the caller handle session shutdown
            if target_app_raw not in ("", "app", "application", "buddy"):
                for alias, target_name in APP_ALIASES.items():
                    if alias in target_app_raw:
                        return VoiceIntent(
                            intent_type=VoiceIntentType.TOOL_REQUEST,
                            normalized_text=raw,
                            tool_name="app.close",
                            tool_arguments={"application": target_name},
                            target=target_name,
                        )

        # 3. Check Memory Commands
        # 3a. Memory Recall: "what is my favorite color?", "what do you remember about my favorite color?"
        recall_patterns = [
            r"\bwhat do you remember about\s+(.+)",
            r"\bwhat is my\s+(.+)",
            r"\bwhat's my\s+(.+)",
            r"\btell me my\s+(.+)",
            r"\bdo you remember my\s+(.+)",
        ]
        for pat in recall_patterns:
            m = re.search(pat, cleaned, re.IGNORECASE)
            if m:
                target_field = m.group(1).strip()
                # Ensure it's not a generic query like "what is your name", "what is the time"
                if not any(target_field.startswith(p) for p in ("the time", "time", "today's date", "date", "battery", "volume", "weather", "current volume")):
                    return VoiceIntent(
                        intent_type=VoiceIntentType.MEMORY_RECALL,
                        normalized_text=raw,
                        target=target_field,
                        memory_content=target_field,
                    )

        # 3b. Memory Forget: "forget my favorite color", "forget that my favorite color is blue"
        forget_match = re.search(r"\b(?:forget|delete the memory about|don't remember)\s+(?:that\s+)?(?:my\s+)?(.+)", cleaned, re.IGNORECASE)
        if forget_match:
            target_field = forget_match.group(1).strip()
            return VoiceIntent(
                intent_type=VoiceIntentType.MEMORY_FORGET,
                normalized_text=raw,
                target=target_field,
                memory_content=target_field,
            )

        # 3c. Memory Remember: "remember that my favorite color is blue", "remember my favorite color is blue"
        remember_match = re.search(r"\bremember\s+(?:that\s+)?(.+)", cleaned, re.IGNORECASE)
        if remember_match and not cleaned.startswith("what do you remember") and not cleaned.startswith("do you remember"):
            content_to_save = remember_match.group(1).strip()
            return VoiceIntent(
                intent_type=VoiceIntentType.MEMORY_REMEMBER,
                normalized_text=raw,
                memory_content=content_to_save,
            )

        # 4. Built-in conversational utilities (Time & Date queries)
        if any(q in cleaned for q in ["what time is it", "current time", "tell me the time", "what's the time"]):
            now_str = datetime.datetime.now().strftime("%I:%M %p")
            return VoiceIntent(
                intent_type=VoiceIntentType.CONVERSATION,
                normalized_text=raw,
                direct_response=f"The current time is {now_str}.",
            )

        if any(q in cleaned for q in ["what's today's date", "what is today's date", "what date is it", "today's date"]):
            today_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
            return VoiceIntent(
                intent_type=VoiceIntentType.CONVERSATION,
                normalized_text=raw,
                direct_response=f"Today is {today_str}.",
            )

        # 5. Default fallback: Safe Natural Language Dialogue
        return VoiceIntent(
            intent_type=VoiceIntentType.CONVERSATION,
            normalized_text=raw,
        )
