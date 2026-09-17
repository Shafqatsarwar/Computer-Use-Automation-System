"""Multi-strategy locator resolution engine for deterministic replay.

Implements resilient element targeting without LLM re-reasoning:
1. Primary: Accessibility role + accessible name (closest to human/AX perception)
2. Secondary fallback: Accessible text / placeholder match
3. Tertiary fallback: CSS / data-attribute selector
"""

from __future__ import annotations
import asyncio
from typing import Any
from playwright.async_api import Locator as PlaywrightLocator, Page

from src.artifact.schema import Locator


class LocatorNotFoundError(Exception):
    """Raised when an element cannot be resolved across all fallback strategies."""
    pass


async def resolve_locator(
    page: Page,
    locator_def: Locator | None,
    timeout_ms: int = 3000,
) -> PlaywrightLocator | None:
    """Attempts to resolve an element using the locator definition and its fallbacks.
    
    Returns a valid Playwright Locator or raises LocatorNotFoundError.
    """
    if locator_def is None:
        return None

    current: Locator | None = locator_def
    attempted_strategies: list[str] = []

    while current is not None:
        strat = current.strategy
        strat_desc = f"{strat}(role={current.role}, name={current.name}, css={current.css})"
        attempted_strategies.append(strat_desc)

        try:
            target: PlaywrightLocator | None = None
            if strat == "role" and current.role:
                if current.name:
                    target = page.get_by_role(current.role, name=current.name)
                else:
                    target = page.get_by_role(current.role)
            elif strat == "text" and current.name:
                target = page.get_by_text(current.name, exact=False)
            elif strat == "css" and current.css:
                target = page.locator(current.css)

            if target is not None:
                # Check visibility and presence within timeout
                first_elem = target.first
                await first_elem.wait_for(state="visible", timeout=timeout_ms)
                # Verify element is attached and has bounding box
                box = await first_elem.bounding_box()
                if box is not None:
                    return first_elem
        except Exception:
            # Fall through to next fallback strategy in chain
            pass

        current = current.fallback

    raise LocatorNotFoundError(
        f"Failed to resolve element after trying strategies: {', '.join(attempted_strategies)}"
    )
