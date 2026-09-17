"""Accessibility observer for Computer-Use Automation System.

Perceives the live browser surface through the accessibility tree:
- Extracts interactive and semantic nodes (role, accessible name, value, description)
- Filters noise while preserving structural context
- Provides an abstraction that works identically on modern web, legacy apps, or desktop AX trees
"""

from __future__ import annotations
from typing import Any
from playwright.async_api import Page


def _trim_a11y_node(node: dict[str, Any], max_depth: int = 5, current_depth: int = 0) -> dict[str, Any] | None:
    """Recursively processes and filters an accessibility node."""
    if not node:
        return None

    role = node.get("role", "")
    name = (node.get("name") or "").strip()
    value = node.get("value")
    children = node.get("children", [])

    # Filter out empty generic non-interactive containers with no name
    is_interactive = role in (
        "button", "link", "textbox", "checkbox", "radio", "combobox",
        "menuitem", "tab", "searchbox", "spinbutton", "listbox", "option", "alert"
    )
    has_content = bool(name or value or role in ("heading", "cell", "row", "table", "banner", "main", "dialog"))

    trimmed_children: list[dict[str, Any]] = []
    if current_depth < max_depth and children:
        for child in children:
            child_trimmed = _trim_a11y_node(child, max_depth, current_depth + 1)
            if child_trimmed:
                trimmed_children.append(child_trimmed)

    if not is_interactive and not has_content and not trimmed_children:
        return None

    res: dict[str, Any] = {"role": role}
    if name:
        res["name"] = name
    if value is not None:
        res["value"] = value
    if node.get("disabled"):
        res["disabled"] = True
    if node.get("focused"):
        res["focused"] = True
    if trimmed_children:
        res["children"] = trimmed_children

    return res


async def observe_surface(page: Page) -> dict[str, Any]:
    """Captures a clean, trimmed accessibility snapshot of the current page.
    
    Returns a dict containing:
    - url: current browser URL
    - title: page title
    - a11y_tree: trimmed hierarchical accessibility tree
    - interactive_elements: flattened list of interactive items (role + name)
    """
    url = page.url
    title = await page.title()
    
    try:
        raw_snapshot = await page.accessibility.snapshot()
    except Exception as e:
        raw_snapshot = {"role": "document", "name": f"Error capturing a11y snapshot: {e}"}

    trimmed_tree = _trim_a11y_node(raw_snapshot) if raw_snapshot else {}

    # Extract flat list of interactive elements for easy LLM reference
    interactive_elements: list[dict[str, str]] = []
    
    def _collect_interactive(node: dict[str, Any]) -> None:
        if not node:
            return
        role = node.get("role", "")
        name = node.get("name", "")
        if role in ("button", "link", "textbox", "checkbox", "radio", "combobox", "option", "tab"):
            if name or role in ("textbox", "button"):
                interactive_elements.append({
                    "role": role,
                    "name": name,
                    "value": str(node.get("value") or ""),
                })
        for child in node.get("children", []):
            _collect_interactive(child)

    if trimmed_tree:
        _collect_interactive(trimmed_tree)

    return {
        "url": url,
        "title": title,
        "a11y_tree": trimmed_tree,
        "interactive_elements": interactive_elements[:50],  # safety cap
    }
