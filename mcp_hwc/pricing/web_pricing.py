from __future__ import annotations

from .models import QuoteResult, ResourceDescriptor


class WebPricingBackend:
    """Playwright-based pricing fallback. Scrapes the HWC price calculator.

    Not yet implemented. Will be built when BSS SDK coverage gaps are identified.
    """

    def quote(self, resources: list[ResourceDescriptor]) -> QuoteResult:
        raise NotImplementedError(
            "Playwright pricing fallback is not yet implemented. "
            "Use the BSS SDK backend instead."
        )
