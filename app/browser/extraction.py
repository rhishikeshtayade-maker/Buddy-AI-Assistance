"""BUDDY Browser Content Extraction.

Extracts bounded visible text, links, forms, and interactive elements from pages.
Wraps all extracted output in untrusted external content delimiters.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.browser.config import BrowserConfig
from app.browser.dom import classify_input_sensitivity
from app.browser.models import FormField, FormFieldSensitivity
from app.browser.sanitizer import WebContentSanitizer

logger = logging.getLogger("buddy.browser.extraction")


class ExtractedLink(BaseModel):
    text: str
    url: str

    model_config = {"extra": "forbid"}


class ExtractedForm(BaseModel):
    form_id: Optional[str] = None
    action: Optional[str] = None
    method: str = "GET"
    fields: List[FormField] = Field(default_factory=list)
    has_credentials: bool = False

    model_config = {"extra": "forbid"}


class ExtractedPageContent(BaseModel):
    url: str
    title: str
    text_content: str
    links: List[ExtractedLink] = Field(default_factory=list)
    forms: List[ExtractedForm] = Field(default_factory=list)
    detected_injections: List[str] = Field(default_factory=list)
    wrapped_prompt_text: str = ""

    model_config = {"extra": "forbid"}


class PageExtractor:
    """Extracts bounded and sanitized structural content from web pages."""

    def __init__(
        self,
        config: Optional[BrowserConfig] = None,
        sanitizer: Optional[WebContentSanitizer] = None,
    ) -> None:
        self._config = config or BrowserConfig()
        self._sanitizer = sanitizer or WebContentSanitizer(self._config)

    def process_extracted_text(
        self,
        url: str,
        title: str,
        raw_text: str,
        max_chars: Optional[int] = None,
    ) -> ExtractedPageContent:
        """Sanitize raw text, scan for prompt injection, and wrap in security tags."""
        limit = max_chars or self._config.browser_max_page_text_chars
        clean_text = self._sanitizer.sanitize_page_text(raw_text, max_chars=limit)
        injections = self._sanitizer.detect_prompt_injection(clean_text)

        wrapped = self._sanitizer.wrap_external_content(
            content=clean_text,
            url=url,
            source="web",
            detected_injections=injections,
        )

        return ExtractedPageContent(
            url=url,
            title=title,
            text_content=clean_text,
            detected_injections=injections,
            wrapped_prompt_text=wrapped,
        )

    def filter_safe_links(
        self,
        raw_links: List[Dict[str, str]],
        max_links: int = 50,
    ) -> List[ExtractedLink]:
        """Filter and truncate extracted hyperlinks."""
        links: List[ExtractedLink] = []
        for item in raw_links[:max_links]:
            text = (item.get("text") or "").strip()[:100]
            href = (item.get("href") or "").strip()[:500]
            if href and not href.startswith(("javascript:", "data:", "vbscript:")):
                links.append(ExtractedLink(text=text or href, url=href))
        return links

    def parse_forms(self, raw_forms: List[Dict[str, Any]]) -> List[ExtractedForm]:
        """Parse and classify form fields by sensitivity."""
        forms: List[ExtractedForm] = []
        for f in raw_forms:
            form_id = f.get("id")
            action = f.get("action")
            method = (f.get("method") or "GET").upper()

            fields: List[FormField] = []
            has_credentials = False

            for field_data in f.get("fields", []):
                fid = str(field_data.get("id") or field_data.get("name") or "field")
                name = field_data.get("name")
                ftype = str(field_data.get("type") or "text")
                label = field_data.get("label")
                placeholder = field_data.get("placeholder")
                required = bool(field_data.get("required", False))

                sensitivity = classify_input_sensitivity(
                    field_id=fid,
                    name=name,
                    field_type=ftype,
                    placeholder=placeholder,
                    label=label,
                )
                if sensitivity in (FormFieldSensitivity.CREDENTIAL, FormFieldSensitivity.PAYMENT):
                    has_credentials = True

                fields.append(
                    FormField(
                        field_id=fid,
                        name=name,
                        field_type=ftype,
                        label=label,
                        sensitivity=sensitivity,
                        required=required,
                        placeholder=placeholder,
                    )
                )

            forms.append(
                ExtractedForm(
                    form_id=form_id,
                    action=action,
                    method=method,
                    fields=fields,
                    has_credentials=has_credentials,
                )
            )
        return forms
