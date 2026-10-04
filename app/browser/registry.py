"""BUDDY Browser Tool Definitions and Registry Integration.

Defines all policy-governed browser automation tools and registers them
into the BUDDY ToolRegistry. All executions flow strictly through ToolExecutor.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.browser.models import BrowserTarget
from app.browser.service import BrowserService
from app.tools.base import Tool
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRiskLevel,
)
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.browser.registry")


# Pydantic Schemas for Strict Input Validation (extra="forbid")
class BrowserOpenInput(BaseModel):
    session_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserCloseInput(BaseModel):
    session_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserNewTabInput(BaseModel):
    session_id: Optional[str] = None
    url: str = "about:blank"
    model_config = {"extra": "forbid"}


class BrowserSwitchTabInput(BaseModel):
    tab_id: str
    session_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserNavigateInput(BaseModel):
    url: str
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserBackInput(BaseModel):
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserForwardInput(BaseModel):
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserReloadInput(BaseModel):
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserInspectInput(BaseModel):
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserFindInput(BaseModel):
    query: str
    role: Optional[str] = None
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserClickInput(BaseModel):
    target_id: Optional[str] = None
    selector: Optional[str] = None
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserDoubleClickInput(BaseModel):
    target_id: Optional[str] = None
    selector: Optional[str] = None
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserTypeInput(BaseModel):
    text: str
    target_id: Optional[str] = None
    selector: Optional[str] = None
    is_sensitive: bool = False
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserPressKeyInput(BaseModel):
    key: str
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserSelectInput(BaseModel):
    value: str
    target_id: Optional[str] = None
    selector: Optional[str] = None
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserScrollInput(BaseModel):
    direction: str = "down"
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserExtractTextInput(BaseModel):
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    max_chars: Optional[int] = None
    model_config = {"extra": "forbid"}


class BrowserScreenshotInput(BaseModel):
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserDownloadInput(BaseModel):
    url: str
    suggested_filename: str = "download.bin"
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserUploadInput(BaseModel):
    file_path: str
    target_id: Optional[str] = None
    selector: Optional[str] = None
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


class BrowserWaitInput(BaseModel):
    seconds: float = 1.0
    session_id: Optional[str] = None
    tab_id: Optional[str] = None
    model_config = {"extra": "forbid"}


# --- TOOL IMPLEMENTATIONS ---

class BrowserOpenTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.open",
            description="Launch an isolated browser session with clean automation profile.",
            input_schema=BrowserOpenInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=30.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserOpenInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = await self._service.open_session(session_id=arguments.get("session_id"))
        return {"session_id": session.session_id, "status": session.status.value}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "session_id" in raw_output


class BrowserCloseTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.close",
            description="Close active browser session and release resources.",
            input_schema=BrowserCloseInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserCloseInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        sid = arguments.get("session_id")
        session = self._service.get_session(sid)
        closed = await self._service.close_session(session.session_id)
        return {"closed": closed, "session_id": session.session_id}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("closed") is True


class BrowserNewTabTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.new_tab",
            description="Open a new tab within the active browser session.",
            input_schema=BrowserNewTabInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=20.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserNewTabInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tab = await self._service.new_tab(
            session_id=arguments.get("session_id"),
            url=arguments.get("url", "about:blank"),
        )
        return {"tab_id": tab.tab_id, "url": tab.url}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "tab_id" in raw_output


class BrowserSwitchTabTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.switch_tab",
            description="Switch active focus to a different tab.",
            input_schema=BrowserSwitchTabInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserSwitchTabInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tab = await self._service.switch_tab(
            tab_id=arguments["tab_id"],
            session_id=arguments.get("session_id"),
        )
        return {"active_tab_id": tab.tab_id, "url": tab.url}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "active_tab_id" in raw_output


class BrowserNavigateTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.navigate",
            description="Navigate active tab to a validated HTTP/HTTPS URL with SSRF protection.",
            input_schema=BrowserNavigateInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=35.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserNavigateInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        page_info = await self._service.navigate(
            url=arguments["url"],
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return page_info.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict) or not raw_output.get("url"):
            return False
        return self._service._verifier.verify_navigation(
            expected_url=arguments["url"],
            current_url=raw_output["url"],
            status_code=raw_output.get("status_code"),
        )


class BrowserBackTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.back",
            description="Navigate back in active tab history.",
            input_schema=BrowserBackInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserBackInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        page_info = await self._service.back(
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return page_info.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "url" in raw_output


class BrowserForwardTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.forward",
            description="Navigate forward in active tab history.",
            input_schema=BrowserForwardInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserForwardInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        page_info = await self._service.forward(
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return page_info.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "url" in raw_output


class BrowserReloadTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.reload",
            description="Reload the current active page.",
            input_schema=BrowserReloadInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=20.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserReloadInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        page_info = await self._service.reload(
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return page_info.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "url" in raw_output


class BrowserInspectTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.inspect",
            description="Inspect active page structure, URL, fingerprint, and sensitive form detection.",
            input_schema=BrowserInspectInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserInspectInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        page_info = await self._service.inspect_page(
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return page_info.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "page_fingerprint" in raw_output


class BrowserFindTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.find",
            description="Discover an interactive target element with confidence scoring and fingerprint binding.",
            input_schema=BrowserFindInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserFindInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        target = await self._service.find_element(
            query=arguments["query"],
            role=arguments.get("role"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return target.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("confidence", 0) >= 0.85


class BrowserClickTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.click",
            description="Click a verified target element on the current page.",
            input_schema=BrowserClickInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserClickInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.click(
            selector=arguments.get("selector"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


class BrowserDoubleClickTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.double_click",
            description="Double click a verified element.",
            input_schema=BrowserDoubleClickInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserDoubleClickInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.double_click(
            selector=arguments.get("selector"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


class BrowserTypeTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.type",
            description="Type text into an input field. Secret fields require elevated confirmation.",
            input_schema=BrowserTypeInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserTypeInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.type_text(
            text=arguments["text"],
            selector=arguments.get("selector"),
            is_sensitive=arguments.get("is_sensitive", False),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


class BrowserPressKeyTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.press_key",
            description="Press an allowlisted keyboard key (ENTER, TAB, ESC, ARROW_DOWN, etc.).",
            input_schema=BrowserPressKeyInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserPressKeyInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.press_key(
            key=arguments["key"],
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


class BrowserSelectTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.select",
            description="Select an option from a dropdown or select menu.",
            input_schema=BrowserSelectInput.model_json_schema(),
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserSelectInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.select_option(
            value=arguments["value"],
            selector=arguments.get("selector"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


class BrowserScrollTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.scroll",
            description="Scroll the active page (up or down).",
            input_schema=BrowserScrollInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserScrollInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.scroll(
            direction=arguments.get("direction", "down"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


class BrowserExtractTextTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.extract_text",
            description="Extract visible text from page, sanitized and wrapped in untrusted data delimiters.",
            input_schema=BrowserExtractTextInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserExtractTextInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        content = await self._service.extract_text(
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
            max_chars=arguments.get("max_chars"),
        )
        return content.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "wrapped_prompt_text" in raw_output


class BrowserScreenshotTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.screenshot",
            description="Capture an in-memory base64 screenshot of active browser tab.",
            input_schema=BrowserScreenshotInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserScreenshotInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        screenshot = await self._service.screenshot(
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return {
            "format": screenshot.format,
            "width": screenshot.width,
            "height": screenshot.height,
            "is_sensitive_page": screenshot.is_sensitive_page,
            "base64_data": screenshot.base64_data[:50] + "...",  # Truncated in output metadata
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "format" in raw_output


class BrowserDownloadTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.download",
            description="Download file to sandboxed directory. Requires explicit confirmation.",
            input_schema=BrowserDownloadInput.model_json_schema(),
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            timeout_seconds=60.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserDownloadInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        path = await self._service.download(
            url_or_target=arguments["url"],
            suggested_filename=arguments.get("suggested_filename", "download.bin"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return {"downloaded_file": str(path), "size_bytes": path.stat().st_size}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict) or not raw_output.get("downloaded_file"):
            return False
        return self._service._verifier.verify_download(Path(raw_output["downloaded_file"]))


class BrowserUploadTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.upload",
            description="Attach a sandboxed local file to a file input element. Requires confirmation.",
            input_schema=BrowserUploadInput.model_json_schema(),
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            timeout_seconds=30.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserUploadInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        ok = await self._service.upload(
            file_path=arguments["file_path"],
            selector=arguments.get("selector"),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return {"uploaded": ok, "file_path": arguments["file_path"]}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("uploaded") is True


class BrowserWaitTool(Tool):
    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser.wait",
            description="Wait for a specified duration (bounded to 10 seconds).",
            input_schema=BrowserWaitInput.model_json_schema(),
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return BrowserWaitInput(**arguments).model_dump()

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._service.wait(
            seconds=arguments.get("seconds", 1.0),
            session_id=arguments.get("session_id"),
            tab_id=arguments.get("tab_id"),
        )
        return res.model_dump()

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and raw_output.get("verification") is True


def register_browser_tools(registry: ToolRegistry, browser_service: BrowserService) -> None:
    """Register all 21 browser automation tools into the ToolRegistry."""
    registry.register_tool(BrowserOpenTool(browser_service))
    registry.register_tool(BrowserCloseTool(browser_service))
    registry.register_tool(BrowserNewTabTool(browser_service))
    registry.register_tool(BrowserSwitchTabTool(browser_service))
    registry.register_tool(BrowserNavigateTool(browser_service))
    registry.register_tool(BrowserBackTool(browser_service))
    registry.register_tool(BrowserForwardTool(browser_service))
    registry.register_tool(BrowserReloadTool(browser_service))
    registry.register_tool(BrowserInspectTool(browser_service))
    registry.register_tool(BrowserFindTool(browser_service))
    registry.register_tool(BrowserClickTool(browser_service))
    registry.register_tool(BrowserDoubleClickTool(browser_service))
    registry.register_tool(BrowserTypeTool(browser_service))
    registry.register_tool(BrowserPressKeyTool(browser_service))
    registry.register_tool(BrowserSelectTool(browser_service))
    registry.register_tool(BrowserScrollTool(browser_service))
    registry.register_tool(BrowserExtractTextTool(browser_service))
    registry.register_tool(BrowserScreenshotTool(browser_service))
    registry.register_tool(BrowserDownloadTool(browser_service))
    registry.register_tool(BrowserUploadTool(browser_service))
    registry.register_tool(BrowserWaitTool(browser_service))
    logger.info("Registered all 21 browser tools into ToolRegistry.")
