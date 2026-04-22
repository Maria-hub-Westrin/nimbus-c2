<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Security Policy

## Supported versions

Only the latest tagged release on the `main` branch is supported with
security updates. Earlier versions are archival and will not receive
patches.

| Version | Supported |
|---------|-----------|
| 1.x     | ✅        |
| < 1.0   | ❌        |

## Reporting a vulnerability

Nimbus-C2 is research software targeting defense decision
support. Security issues — in the narrow sense (memory-safety,
authentication, injection) or the broad sense (adversarial inputs
that cause the uncertainty layer to mis-classify novel-tactic
scenarios as in-distribution) — should be reported privately,
**not** via public GitHub issues.

Please open a private security advisory via GitHub's "Security" tab
on this repository, or contact the maintainer listed in `AUTHORS`
directly.

## Response target

Initial acknowledgement within **5 business days**.
Triage and preliminary assessment within **14 business days**.
Patch or mitigation on a schedule proportionate to severity.

## Scope

In scope:

- Code in `src/`, `tests/`, and `scripts/` of this repository.
- Calibration artifacts in `data/` that influence runtime thresholds.
- Adversarial inputs that cause the assurance layer or safety shield
  to silently fail-open (i.e. authorize an action that the shield
  specification requires to be vetoed).

Out of scope:

- Third-party dependencies (report to their upstream).
- Issues that require physical access to a deployed host.
- Theoretical decision-theoretic arguments that are not accompanied
  by a reproducing input.

## Disclosure

After a patch ships, reporters who wish to be credited will be
acknowledged in the release notes.
