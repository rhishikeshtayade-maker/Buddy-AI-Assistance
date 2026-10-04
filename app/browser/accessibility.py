"""BUDDY Browser Accessibility Tree Inspection.

Provides controlled, bounded extraction of browser accessibility snapshots.
Enables reliable target discovery using standard WAI-ARIA roles and accessible names.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("buddy.browser.accessibility")


class AccessibilityNode(BaseModel):
    """Semantic accessibility node representation."""
    role: str
    name: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = None
    disabled: bool = False
    focused: bool = False
    checked: Optional[bool] = None
    children: List[AccessibilityNode] = Field(default_factory=list)

    model_config = {
        "extra": "forbid",
    }


def parse_accessibility_tree(
    raw_node: Dict[str, Any],
    max_nodes: int = 200,
    current_count: int = 0,
) -> Tuple[Optional[AccessibilityNode], int]:
    """Recursively parse Playwright accessibility snapshot dictionary into typed tree with bounded depth/node count."""
    if not raw_node or current_count >= max_nodes:
        return None, current_count

    role = str(raw_node.get("role", "generic"))
    name = raw_node.get("name")
    description = raw_node.get("description")
    value = str(raw_node.get("value")) if raw_node.get("value") is not None else None
    disabled = bool(raw_node.get("disabled", False))
    focused = bool(raw_node.get("focused", False))
    checked = raw_node.get("checked")

    current_count += 1
    children: List[AccessibilityNode] = []

    for child_dict in raw_node.get("children", []):
        if current_count >= max_nodes:
            break
        child_node, current_count = parse_accessibility_tree(
            child_dict,
            max_nodes=max_nodes,
            current_count=current_count,
        )
        if child_node:
            children.append(child_node)

    node = AccessibilityNode(
        role=role,
        name=name,
        description=description,
        value=value,
        disabled=disabled,
        focused=focused,
        checked=checked if isinstance(checked, bool) else None,
        children=children,
    )
    return node, current_count


def flatten_interactive_nodes(node: AccessibilityNode) -> List[AccessibilityNode]:
    """Filter accessibility tree for interactive elements (buttons, links, textboxes, comboboxes)."""
    interactive_roles = {
        "button",
        "link",
        "textbox",
        "combobox",
        "checkbox",
        "radio",
        "menuitem",
        "tab",
        "searchbox",
    }
    results = []
    if node.role in interactive_roles and (node.name or node.value):
        results.append(node)

    for child in node.children:
        results.extend(flatten_interactive_nodes(child))

    return results
