# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Situation Report (SITREP) generator — deterministic template.

The SITREP is the human-facing summary rendered in the commander's UI.
It carries:

    * headline        — one-sentence situation summary
    * posture         — current autonomy mode with rationale
    * threats_summary — what's inbound, what's been engaged
    * recommendation  — which COA the system recommends and why
    * assurance_note  — SA-health status in plain language
    * follow_on_note  — wave-forecast implications
    * alerts          — surface-visible sensor/assurance alerts

**Numeric correctness is non-negotiable.** The SITREP template fills
slots with numbers from the engine output; no number in the SITREP
ever originates from free-form text generation. If an LLM layer is
later attached (behind a feature flag), it is permitted to rewrite
the *prose* fields only; the numeric fields are locked to the
engine's structured output.

This is what makes the SITREP safe to show a commander: the words
may be polished by a language model, but the counts, the Pks, the
survival percentages never pass through one.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from .assurance import AssuranceReport, AutonomyMode
from .coa_generator import COA, COALabel
from .wave_forecaster import WaveForecast


class SITREPSource(str, Enum):
    """Record of which layer produced the final prose."""
    TEMPLATE = "template"          # deterministic, offline
    LLM_ENHANCED = "llm_enhanced"  # reserved for Stage-4 LLM prose rewrite


@dataclass(frozen=True)
class SITREP:
    headline: str
    posture: str
    threats_summary: str
    recommendation: str
    assurance_note: str
    follow_on_note: str
    alerts: list[str] = field(default_factory=list)
    source: SITREPSource = SITREPSource.TEMPLATE

    def as_dict(self) -> dict:
        return {
            "headline": self.headline,
            "posture": self.posture,
            "threats_summary": self.threats_summary,
            "recommendation": self.recommendation,
            "assurance_note": self.assurance_note,
            "follow_on_note": self.follow_on_note,
            "alerts": list(self.alerts),
            "source": self.source.value,
        }


# --------------------------------------------------------------------------- #
# Template generation                                                         #
# --------------------------------------------------------------------------- #

def _posture_for_mode(mode: AutonomyMode) -> str:
    return {
        AutonomyMode.AUTONOMOUS: "AUTONOMOUS — system authorised to execute "
                                 "without operator confirmation.",
        AutonomyMode.ADVISE:     "ADVISE — system proposes; operator confirms "
                                 "before execution.",
        AutonomyMode.DEFER:      "DEFER — system has withdrawn from the "
                                 "decision; full operator control.",
    }[mode]


def _headline_for_mode(mode: AutonomyMode, n_threats: int, stakes: float) -> str:
    if n_threats == 0:
        return "No inbound threats. Nominal posture."
    stakes_tag = "high-stakes" if stakes >= 0.7 else (
        "elevated" if stakes >= 0.4 else "nominal"
    )
    return (
        f"{n_threats} inbound track(s), {stakes_tag}. "
        f"Autonomy: {mode.value}."
    )


def _recommendation_text(coas: Sequence[COA], mode: AutonomyMode) -> str:
    if not coas:
        return "No feasible engagement plan available. Reassess inventory and ROE."
    rec = next((c for c in coas if c.label == COALabel.RECOMMENDED), coas[0])
    action_verb = {
        AutonomyMode.AUTONOMOUS: "Executing",
        AutonomyMode.ADVISE:     "Proposing",
        AutonomyMode.DEFER:      "Presenting for operator selection",
    }[mode]
    n = len(rec.assignments)
    cov = rec.predicted_coverage * 100
    return (
        f"{action_verb} RECOMMENDED COA: {n} engagement(s), "
        f"{cov:.0f}% coverage, follow-on risk {rec.risk_if_follow_on:.2f}. "
        f"Two alternatives available: RESERVE_CONSERVING and RISK_MINIMIZING."
    )


def _assurance_note(report: AssuranceReport) -> str:
    """Verbalise the SA-health signal without revealing raw reason strings
    (the full reason list is separately surfaced in the UI)."""
    sa = report.sa_health
    complexity = report.situation_complexity
    tqi = report.track_quality_index
    if sa >= 85:
        quality = "high"
    elif sa >= 60:
        quality = "adequate"
    elif sa >= 40:
        quality = "degraded"
    else:
        quality = "poor"
    return (
        f"SA-health {sa:.0f}% ({quality}). Track quality index {tqi:.2f}; "
        f"situation complexity {complexity:.2f}."
    )


def _follow_on_note(forecast: WaveForecast) -> str:
    if not forecast.sectors or forecast.follow_on_likelihood < 0.10:
        return "No significant follow-on wave predicted in the forecast window."
    hot = [s for s in forecast.sectors if s.arrival_prob_60s >= 0.30]
    if not hot:
        return (
            f"Follow-on likelihood {forecast.follow_on_likelihood:.0%}. "
            "No single sector dominates; no concentration expected."
        )
    sector_names = ", ".join(s.sector_id for s in hot)
    return (
        f"Follow-on likelihood {forecast.follow_on_likelihood:.0%}. "
        f"Expected concentration in sector(s): {sector_names}. "
        f"Recommended reserve weighted toward those bearings."
    )


def _threats_summary(
    n_total: int,
    n_engaged: int,
    total_value: float,
    engaged_value: float,
) -> str:
    if n_total == 0:
        return "No inbound tracks."
    leaked = n_total - n_engaged
    pct_val = (engaged_value / total_value * 100) if total_value > 0 else 0.0
    if leaked == 0:
        return (
            f"{n_total} inbound track(s), total value {total_value:.0f}. "
            f"All tracks matched with engagement ({pct_val:.0f}% of value)."
        )
    return (
        f"{n_total} inbound track(s), total value {total_value:.0f}. "
        f"{n_engaged} matched ({pct_val:.0f}% of value); "
        f"{leaked} unmatched — see per-track reason list."
    )


# --------------------------------------------------------------------------- #
# Top-level                                                                   #
# --------------------------------------------------------------------------- #

def build_offline_sitrep(
    assurance: AssuranceReport,
    forecast: WaveForecast,
    coas: Sequence[COA],
    n_threats: int,
    total_threat_value: float,
) -> SITREP:
    """Produce a fully-populated SITREP from the engine output.

    Pure, deterministic, offline. Identical inputs yield an identical
    SITREP across every run, which is the contract the API layer and
    the test suite rely on.
    """
    rec = next((c for c in coas if c.label == COALabel.RECOMMENDED), None)
    if rec is not None:
        n_engaged = len({a.threat_id for a in rec.assignments})
        sum(
            a.utility for a in rec.assignments
        )  # not directly value, but a proxy; the coverage % is the authoritative figure.
    else:
        n_engaged = 0

    # Use the authoritative coverage fraction for the value display.
    authoritative_engaged_value = (
        rec.predicted_coverage * total_threat_value if rec is not None else 0.0
    )

    return SITREP(
        headline=_headline_for_mode(
            assurance.autonomy_mode, n_threats, assurance.stakes,
        ),
        posture=_posture_for_mode(assurance.autonomy_mode),
        threats_summary=_threats_summary(
            n_threats, n_engaged, total_threat_value, authoritative_engaged_value,
        ),
        recommendation=_recommendation_text(coas, assurance.autonomy_mode),
        assurance_note=_assurance_note(assurance),
        follow_on_note=_follow_on_note(forecast),
        alerts=list(assurance.alerts),
        source=SITREPSource.TEMPLATE,
    )


__all__ = [
    "SITREP",
    "SITREPSource",
    "build_offline_sitrep",
]
