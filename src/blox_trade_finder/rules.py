"""Alert rules: user-defined conditions + per-rule delivery frequency.

Each rule describes WHICH matching trades it cares about (min profit, trades
giving item X, trades asking for item X, verdict, confidence, demand, source…)
and HOW OFTEN to email about them (`frequency_minutes`: 0 = instant, N =
batched digest every N minutes). All set conditions must hold (AND semantics);
unset conditions are ignored. A rule with no conditions matches every trade.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from blox_trade_finder.models import Match


def _expand_permanent(names: list[str]) -> set[str]:
    """Lowercased names, plus 'permanent X' variants for non-permanent names."""
    out: set[str] = set()
    for name in names:
        lowered = name.strip().lower()
        if not lowered:
            continue
        out.add(lowered)
        if not lowered.startswith("permanent "):
            out.add(f"permanent {lowered}")
    return out


class AlertRule(BaseModel):
    """One alert rule: conditions ANDed together + its own delivery frequency."""

    name: str
    enabled: bool = True
    # 0 = send an email the moment a matching trade is found;
    # N > 0 = batch matching trades and send at most one email every N minutes.
    frequency_minutes: int = 0

    # --- value / profit conditions (all optional; None = don't care) ---
    min_profit: int | None = None          # delta (received - given) in value units
    min_profit_pct: float | None = None    # profit as a fraction of given value (0.5 = +50%)
    min_get_value: int | None = None       # total value the trade GIVES you
    max_give_value: int | None = None      # total value YOU must give up

    # --- item conditions ---
    # Trade must GIVE you at least one of these items.
    gives_items: list[str] = Field(default_factory=list)
    # Trade must ASK FOR (want) at least one of these items.
    wants_items: list[str] = Field(default_factory=list)
    # Whether "Dragon" in the lists above also matches "Permanent Dragon".
    include_permanent: bool = True

    # --- quality conditions ---
    verdicts: list[str] = Field(default_factory=list)  # e.g. ["win"]; empty = any
    min_confidence: int | None = None
    min_demand: int | None = None

    # --- source condition ---
    sources: list[str] = Field(default_factory=list)  # empty = any source

    def _names(self, names: list[str]) -> set[str]:
        if self.include_permanent:
            return _expand_permanent(names)
        return {n.strip().lower() for n in names if n.strip()}

    def matches(self, m: Match) -> bool:
        if not self.enabled:
            return False
        if self.min_profit is not None and m.delta < self.min_profit:
            return False
        if self.min_profit_pct is not None and m.profit_pct < self.min_profit_pct:
            return False
        if self.min_get_value is not None and m.get_value < self.min_get_value:
            return False
        if self.max_give_value is not None and m.give_value > self.max_give_value:
            return False
        if self.gives_items:
            given = {item.name.lower() for item in m.listing.give}
            if not (given & self._names(self.gives_items)):
                return False
        if self.wants_items:
            wanted = {item.name.lower() for item in m.listing.want}
            if not (wanted & self._names(self.wants_items)):
                return False
        if self.verdicts and m.verdict not in self.verdicts:
            return False
        if self.min_confidence is not None and m.confidence < self.min_confidence:
            return False
        if self.min_demand is not None and m.demand < self.min_demand:
            return False
        if self.sources and m.listing.source not in self.sources:
            return False
        return True


def route_matches(
    matches: list[Match], rules: list[AlertRule]
) -> tuple[dict[str, list[Match]], list[Match]]:
    """Route each match to every rule it satisfies.

    Returns (per_rule, unclaimed):
      per_rule  — rule name -> list of matches that rule claimed (a match may
                  appear under several rules);
      unclaimed — matches no enabled rule claimed (they fall back to the
                  default digest).
    """
    per_rule: dict[str, list[Match]] = {r.name: [] for r in rules if r.enabled}
    unclaimed: list[Match] = []
    for m in matches:
        claimed = False
        for rule in rules:
            if rule.enabled and rule.matches(m):
                per_rule[rule.name].append(m)
                claimed = True
        if not claimed:
            unclaimed.append(m)
    return per_rule, unclaimed
