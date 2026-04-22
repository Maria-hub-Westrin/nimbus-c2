<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Migration — from AI-Based-Counter-Drone-Situational-Awareness to Nimbus-C2

This document is the operational playbook for retiring the old
repository cleanly while preserving provenance. Follow the steps in
order. Do **not** delete the old repository — professional practice is
to archive it, mark it superseded, and point it at the new home.

## Why we are migrating

The old repo has repository-wide corruption: a git-merge accident
collapsed every `.py` and `.md` file's newlines into spaces, turning
67 source files into single-line comments that don't parse. While the
author's local working copy still runs, anyone cloning the public repo
cannot build or run it. Partial restoration would leave a hybrid of
old hackathon code and fresh stage-gated code with inconsistent
architectural standards. A clean cut from a freshly-architected repo
is the faster path to a SAAB-pitchable state.

## Migration steps

### 1. Create the new repository

Create a new public GitHub repository named `nimbus-c2`:

```
https://github.com/<your-username>/nimbus-c2
```

Do **not** initialise it with a README or LICENSE from GitHub; we will
push the fully-formed pack as the first commit.

### 2. Push the Nimbus-C2 pack to the new repository

From the unzipped `nimbus-c2/` directory:

**Windows PowerShell:**
```powershell
Set-Location nimbus-c2
git init
git add -A
git commit -s -m "Initial commit: Stage 0 + Stage 1 complete

Stage-gated reliability-aware C2 decision engine per STRATEGY.md.
110 tests green on Python 3.10/3.11/3.12 matrix.
MILP TEWA core with parity vs Hungarian and 1000-run determinism gate.
Epistemic-uncertainty and offline-RL layers scaffolded for Stages 2-3.
"
git branch -M main
git remote add origin https://github.com/<your-username>/nimbus-c2.git
git push -u origin main
```

### 3. Verify CI runs green on the new repository

On GitHub, navigate to **Actions**. The workflow defined in
`.github/workflows/ci.yml` should run automatically and turn green
across the Python 3.10 / 3.11 / 3.12 matrix. If it does not:

- Check that `actions: read` and `contents: read` permissions are
  granted by default on the repo's Settings → Actions → General.
- Re-run the failing job; first runs on fresh repos sometimes hit
  cache-not-yet-populated hiccups.

When the green checkmark appears on the `main` branch badge, Stage 1
is publicly verifiable, not just privately claimed.

### 4. Mark the old repository archived

On the old repo
(`AI-Based-Counter-Drone-Situational-Awareness`):

1. **Settings → General → Archive this repository.** This makes it
   read-only but preserves all history and issues. The archived badge
   signals to visitors the repo is no longer the canonical home.
2. **Edit the old README.md.** Replace its contents with a short
   notice:

```markdown
# Archived — superseded by Nimbus-C2

This repository was the hackathon prototype for a reliability-aware
counter-drone C2 decision engine. It has been superseded by
**[Nimbus-C2](https://github.com/<your-username>/nimbus-c2)**, a
stage-gated reimplementation with a deterministic MILP core,
measurable reliability layers, and a formal plan.

See `nimbus-c2/STRATEGY.md` for the rationale and roadmap.
```

3. **Pin the Nimbus-C2 repository** on your GitHub profile so
   visitors land on the canonical project first.

### 5. Update any external references

Grep for references to the old repo URL in your:

- LinkedIn / academic profile pages.
- Past CV / portfolio PDFs.
- Anthropic / SAAB / other submitted decks.
- Zenodo / Figshare / arXiv entries (if any).

Replace with the Nimbus-C2 URL. GitHub's archive badge on the old repo
will handle the soft-redirect for casual visitors, but curated
references should point at the new home directly.

### 6. Create a Zenodo DOI for Nimbus-C2 (recommended)

On Zenodo (free, CERN-operated):

1. Log in with GitHub; authorise the Zenodo–GitHub integration.
2. Navigate to https://zenodo.org/account/settings/github/ and toggle
   the Nimbus-C2 repo to "On".
3. On the Nimbus-C2 repo, tag a release: `git tag v1.0.0 && git push
   --tags`. Zenodo will auto-archive the release and mint a DOI.
4. Update `CITATION.cff` in a follow-up commit to include the DOI
   under `identifiers:`.

The DOI is what makes the project **citable in academic work** in a way
that survives GitHub outages and repository transfers. It is the strong
attribution channel that MIT's clause-1 notice requirement cannot
provide alone.

## What is **not** carried forward from the old repo

The following were deliberately left behind:

- The RL-overlay PyTorch networks (`policy_network.pth`,
  `value_network.pth`, `doctrine_network.pth`). These are Stage-3
  territory under the new plan; if useful training data exists, it will
  be regenerated under the shield-wrapped offline-RL regime in Stage 3.
- The genetic optimiser (`genetic_optimizer.py`) — the MILP primary
  solver supersedes it.
- The red-team module (`red_team.py`) — will be reintroduced in Stage 3
  as adversarial coverage for the shield validation suite.
- The doctrine-comparison sweeps — research scaffolding, not pitch
  material.
- The OpenSky adapter (`opensky_adapter.py`) and the live Baltic JSON
  scenarios — useful for future data-integration work but not in the
  Stage-1/2 critical path.
- The LLM-assisted SITREP rewriter. The new SITREP is deterministic
  template-only; if an LLM rewrite is later desired, it will enter as
  an opt-in Stage-4 feature with the numeric fields remaining locked.

## What **is** carried forward

Everything in the Nimbus-C2 repository was written fresh from the
documented architecture as the specification. The concepts that
survive — scoring formula, SA-health math, three-COA structure, wave
forecaster partition, SITREP field layout — were already authoritatively
captured in `docs/ARCHITECTURE.md` and `docs/SAAB_ALIGNMENT.md` of the
old repo before corruption, and those docs informed the new
implementation. No byte of source code is ported.

## After migration

- Open Nimbus-C2 issues for any Stage-2 work (conformal prediction,
  OOD detector, ensemble-based epistemic). Tag them with
  `stage:2` labels.
- Resist the temptation to jump ahead. The stage gates exist so that
  when SAAB asks "how do you know your conformal coverage is ≥90%?"
  you can answer with a CI green badge, not a story.
