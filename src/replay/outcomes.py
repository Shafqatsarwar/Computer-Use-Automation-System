"""Known outcomes and error taxonomy matcher for deterministic replay.

Distinguishes between:
- Business outcomes (e.g. user locked out, record not found) -> legitimate business result
- Recoverable runtime states (e.g. transient slow network, dismissable modal)
- Hard failures (e.g. unexpected state, corrupt session)
"""

from __future__ import annotations
from typing import Literal
from playwright.async_api import Page
from src.artifact.schema import KnownOutcome


class OutcomeMatchResult:
    def __init__(
        self,
        matched: bool,
        classification: Literal["business_outcome", "recoverable", "hard_failure"] = "hard_failure",
        outcome_code: str | None = None,
        message: str = "",
    ) -> None:
        self.matched = matched
        self.classification = classification
        self.outcome_code = outcome_code
        self.message = message


async def check_known_outcomes(
    page: Page,
    known_outcomes: list[KnownOutcome],
) -> OutcomeMatchResult | None:
    """Inspects the live page to see if any declared KnownOutcome matches."""
    if not known_outcomes:
        return None

    try:
        # Extract page text and current URL
        current_url = page.url
        body_text = await page.inner_text("body")
    except Exception:
        return None

    for outcome in known_outcomes:
        rule = outcome.match
        matched = False

        if rule.startswith("text_contains:"):
            target_str = rule[len("text_contains:"):].strip()
            if target_str.lower() in body_text.lower():
                matched = True
        elif rule.startswith("url_contains:"):
            target_str = rule[len("url_contains:"):].strip()
            if target_str.lower() in current_url.lower():
                matched = True

        if matched:
            return OutcomeMatchResult(
                matched=True,
                classification=outcome.classification,
                outcome_code=outcome.outcome_code,
                message=outcome.message,
            )

    return None
