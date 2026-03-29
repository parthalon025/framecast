# GitHub Actions Integrations Research

**Date:** 2026-03-20
**Project:** FrameCast (Python + Node.js + pi-gen, Raspberry Pi photo frame)
**Scope:** CI integrations, Claude Code CI, CD/DevOps patterns
**Context:** Feature-frozen v2.0 project, solo developer, learning DevOps

---

## Part 1: GitHub Actions Marketplace Integrations

### Tier 1: High Value — Recommend Implementing

#### actionlint (GitHub Actions Workflow Linter)
- **What:** Static checker for GitHub Actions workflow files — catches type errors in expressions, validates action inputs/outputs, integrates with shellcheck/pyflakes for embedded scripts, detects script injection vulnerabilities
- **Stars:** 3.7k | **Last release:** v1.7.11 (2026-02-14) | **Actively maintained**
- **Value for FrameCast:** High. You have multiple workflow files and already lint everything else (ruff, shellcheck, mypy). This closes the gap on workflow file quality. Catches real bugs: undefined matrix properties, type mismatches in `${{ }}` expressions, untrusted variable usage
- **Effort:** Minimal — single `actionlint` command, auto-discovers `.github/workflows/`
- **Solo developer verdict:** Worth it. Catches mistakes before they waste CI minutes
- **Action:** `rhysd/actionlint` or just install the binary

#### commitlint (Conventional Commits Enforcement)
- **What:** Lints commit messages against Conventional Commits spec (`feat:`, `fix:`, `chore:`, etc.)
- **Stars:** 17k+ (conventional-changelog/commitlint) | **Actively maintained**
- **Value for FrameCast:** Medium-high. You already use release-please, which depends on conventional commits to generate changelogs and version bumps. Without commitlint, a malformed commit message silently breaks the release pipeline. This closes that gap
- **Effort:** Low — `wagoid/commitlint-github-action@v6` Docker action, zero config if you accept defaults (`config-conventional`)
- **Solo developer verdict:** Worth it specifically because release-please depends on it. Without enforcement, one slip means a missed release entry
- **Caveat:** Requires `fetch-depth: 0` on checkout

#### Claude Code Action (AI PR Review + Automation)
- **What:** Official Anthropic GitHub Action (`anthropics/claude-code-action@v1`). Runs Claude Code in CI for PR review, issue triage, code implementation, documentation sync. Reads your `CLAUDE.md` for project standards
- **Stars:** 6.4k | **81 contributors** | **GA v1.0 (Aug 2025)** | **MIT license**
- **Value for FrameCast:** High. You already use Claude Code extensively with hooks, skills, and plugins locally. This extends that to CI. Key use cases:
  - **Auto PR review:** Posts inline comments on code quality, bugs, security on every PR
  - **Security-focused review:** OWASP Top 10 analysis with severity ratings (separate action: `anthropics/claude-code-security-review`)
  - **Issue triage:** Auto-label and categorize new issues
  - **Documentation sync:** Auto-update docs when API routes change
  - **Scheduled maintenance:** Weekly repo health checks
- **Setup:** `/install-github-app` from Claude Code terminal, or manual: install GitHub App + add `ANTHROPIC_API_KEY` secret
- **Cost:** Anthropic API tokens per run + GitHub Actions minutes. Control with `--max-turns` and `paths:` filters
- **CLAUDE.md integration:** Yes — Claude reads your repo's CLAUDE.md for standards and conventions
- **Solo developer verdict:** Strong recommend. This is the highest-leverage integration on this list. You already have the muscle memory for Claude Code conventions. The PR review catches what your existing linters miss (logic bugs, architectural drift, security implications). The security review action is especially valuable given FrameCast runs on a device in someone's home
- **Key workflows:**
  - `on: pull_request` with prompt for code review
  - `on: issues [opened]` for auto-triage
  - `on: schedule` for weekly maintenance
  - Path-specific triggers for security-sensitive files

#### SBOM Generation (CycloneDX via cdxgen)
- **What:** Generates Software Bill of Materials listing all dependencies, their versions, and licenses
- **Tool:** `cdxgen` — multi-language (Python + Node.js in one tool), CycloneDX format output
- **Stars:** 1.8k+ (cdxgen/cdxgen) | **Actively maintained**
- **Value for FrameCast:** Medium-high. You already have pip-audit + npm audit + gitleaks + cosign signing. SBOM is the missing piece that ties it all together — it's the receipt that says "here's exactly what's in this build." CycloneDX format integrates with vulnerability databases. Increasingly required/expected for supply chain transparency
- **Effort:** Low — single step in CI, ~90 seconds for a project this size
- **Solo developer verdict:** Worth it if you care about supply chain completeness (you clearly do, given cosign + gitleaks + pip-audit). It's the document that makes all the other security tools auditable. Skip if the badge/compliance angle doesn't matter
- **Format choice:** CycloneDX over SPDX — better for security use cases, OWASP-backed

#### GitHub Artifact Attestations (Build Provenance)
- **What:** Generates SLSA build provenance attestations for your artifacts using Sigstore. Links artifacts to the exact workflow run that built them
- **Action:** `actions/attest-build-provenance@v3` (wrapper on `actions/attest`)
- **Value for FrameCast:** Medium-high. You already have cosign keyless signing. Attestations go further — they prove not just "this artifact is signed" but "this artifact was built by this workflow, from this commit, on this runner." SLSA Build Level 2 out of the box, Level 3 with reusable workflows
- **Effort:** Low — add one step after build, requires `id-token: write` + `attestations: write` permissions
- **Availability:** Free for public repos on all plans. Private repos require Enterprise Cloud
- **Solo developer verdict:** Worth it if the repo is public. Natural extension of your existing cosign signing. Adds verifiable provenance to your pi-gen images
- **Note:** As of v4, this is a wrapper on `actions/attest` — new implementations should use that directly

---

### Tier 2: Moderate Value — Consider

#### Trivy (Filesystem Vulnerability Scanning)
- **What:** Scans filesystem for vulnerabilities in dependencies, misconfigurations, and secrets. Covers container images, filesystems, git repos
- **Stars:** 24k+ | **Action:** `aquasecurity/trivy-action`
- **Value for FrameCast:** Moderate. You already have pip-audit + npm audit + gitleaks. Trivy adds: filesystem-level scanning (catches things beyond pip/npm), misconfiguration detection, and broader vulnerability database coverage. It's a superset of what you have
- **CRITICAL WARNING:** In March 2026, 75 of 76 version tags in `aquasecurity/trivy-action` were hijacked by an attacker — only `@0.35.0` was unaffected. This is an active supply chain compromise. **Pin to a specific SHA, not a tag, if you use this.** Or install Trivy directly via `apt`/binary and skip the action entirely
- **Solo developer verdict:** The March 2026 compromise is concerning. If you add this, install Trivy directly (`apt-get install trivy` or download binary) rather than using the compromised action. The scanning value is real but overlaps with pip-audit/npm audit/gitleaks

#### OSSF Scorecard
- **What:** Automated supply chain security scoring. Analyzes your repo against security heuristics (pinned dependencies, branch protection, SAST, etc.) and generates a 0-10 score per category
- **Stars:** 4.5k+ | **Action:** `ossf/scorecard-action`
- **Value for FrameCast:** Moderate. You already implement most of what Scorecard checks (SHA-pinned actions, branch protection, SAST via CodeQL, signed releases). Running it would confirm your existing posture and surface any gaps. The badge is nice for visibility
- **Effort:** Low — one workflow on schedule, publishes results to Security tab
- **Solo developer verdict:** Run it once manually to see your score. If you're already at 8+/10, the ongoing CI job adds noise. Worth adding if you want the badge for the README or if you discover surprising gaps

#### StepSecurity harden-runner
- **What:** Runtime security agent for CI runners — monitors network egress, file integrity, process activity. Like an EDR for your GitHub Actions workflow
- **Stars:** 2.5k+ | **Secures 8M+ workflow runs/week**
- **Value for FrameCast:** Low-moderate. Protects against supply chain attacks *during CI execution* — if a compromised action tries to exfiltrate your secrets, harden-runner blocks it. Real value given the Trivy tag hijacking incident above
- **Effort:** Add one step to each job. Free tier available
- **Solo developer verdict:** Nice-to-have. The Trivy compromise shows this threat is real, but for a solo dev on a photo frame project, the risk/reward is marginal. Consider it if you're using many third-party actions you don't fully trust

#### PR Size Labeling
- **What:** Auto-labels PRs as XS/S/M/L/XL based on diff size
- **Actions:** `codelytv/pr-size-labeler`, `pascalgn/size-label-action`, GitHub's `actions/labeler`
- **Value for FrameCast:** Low-moderate. Useful as a visual cue to keep PRs small. On a solo project, you already know your PR sizes
- **Solo developer verdict:** Skip unless you want the visual discipline. Zero cost to add, zero cost to skip

#### Reusable Workflows
- **What:** DRY pattern — define a workflow once, call it from multiple repos
- **Value for FrameCast:** Low for a single project. High if you apply your CI patterns across your 36 repos
- **Solo developer verdict:** Not worth it for FrameCast alone. Worth considering as a cross-repo pattern if you want to standardize CI across your project repos. The investment pays off at 3+ repos sharing the same patterns

---

### Tier 3: Low Value / Overkill for This Project

#### Renovate (vs Dependabot)
- **What:** Dependency update bot with 90+ package managers, automerge, grouping, merge confidence scoring
- **Comparison:** Dependabot covers 30+ ecosystems (sufficient for pip + npm + github-actions), is built into GitHub with zero setup. Renovate adds: group PRs, automerge with rules, dependency dashboard, regex managers for non-standard files
- **Solo developer verdict:** Stay with Dependabot. Renovate's power features (grouping, merge confidence, multi-platform) solve problems you don't have. Dependabot is free, zero-config, and covers your pip/npm/github-actions ecosystems. Switching adds config complexity with marginal gain

#### License Compliance Scanning (FOSSA, FOSSology, ScanCode)
- **What:** Scans dependencies for license compatibility, flags copyleft/restricted licenses
- **Solo developer verdict:** Overkill. You're a solo dev on a personal project. If you want a quick check, run `pip-licenses` locally once. CI-level license scanning is for organizations with legal compliance requirements

#### Stale Issue/PR Bot
- **What:** `actions/stale` — auto-closes issues/PRs after inactivity period
- **Solo developer verdict:** Skip. On a solo project you know your backlog. The bot adds noise and is widely criticized in the open source community for being hostile to legitimate issues

#### OpenSSF Best Practices Badge
- **What:** Self-assessment badge covering 67 criteria (passing level) across security, quality, reporting
- **Solo developer verdict:** Educational but not actionable for CI. Fill it out once manually to find gaps. Don't automate it. The value is the self-assessment process, not the badge

#### OPA/Rego (Compliance as Code)
- **What:** Policy engine for enforcing rules on infrastructure/config as code
- **Solo developer verdict:** Enterprise overkill. Your existing branch protection + hookify + gitleaks pre-commit already enforce your policies. OPA is for organizations managing hundreds of repos with centralized policy requirements

#### DORA Metrics Dashboard
- **What:** Tracks deployment frequency, lead time, MTTR, change failure rate
- **Solo developer verdict:** Overkill for a feature-frozen solo project. These metrics matter for teams optimizing delivery pipelines. You'd be measuring yourself against yourself. If curious, check `mikaelvesavuori/github-dora-metrics` for a lightweight approach

#### Feature Flags (LaunchDarkly, Unleash)
- **What:** Gradual feature rollouts with flag-based toggling
- **Solo developer verdict:** Overkill. Feature-frozen project deploying to a single Pi. Your OTA update system with rollback is sufficient

---

## Part 2: Claude Code CI Integrations

### Available Official Actions

| Action | Purpose | Stars |
|--------|---------|-------|
| `anthropics/claude-code-action@v1` | General-purpose PR/issue automation | 6.4k |
| `anthropics/claude-code-security-review` | Security-focused PR analysis | N/A |
| `anthropics/claude-code-base-action` | Low-level base action for custom builds | N/A |

### Claude Code Action Capabilities

**Interactive Mode** (responds to `@claude` mentions):
- Answer questions about code, architecture, patterns
- Implement fixes, refactoring, features
- Create PRs from issue descriptions

**Automation Mode** (runs on events with explicit prompt):
- Auto-review every PR (code quality, bugs, security, performance)
- Path-specific reviews (trigger only when critical files change)
- External contributor reviews (stricter criteria for first-time contributors)
- Custom review checklists (enforce team standards)
- Scheduled maintenance (weekly health checks)
- Issue triage and labeling
- Documentation sync on API changes
- Security-focused reviews (OWASP Top 10 aligned)

### Claude Code Security Review
- **Separate action:** `anthropics/claude-code-security-review`
- **What:** Dedicated security analysis — examines diffs for vulnerabilities, rates severity, suggests remediation
- **Filtering:** Advanced noise reduction to minimize false positives
- **Caveat:** Not hardened against prompt injection — only use on trusted PRs (enable "Require approval for all external contributors")
- **Default model:** Opus 4.1

### How Claude Code Action Interacts with CLAUDE.md
- Claude reads the repo's `CLAUDE.md` file for project standards and conventions
- Your existing CLAUDE.md with architecture docs, module descriptions, and conventions carries directly into CI reviews
- This means Claude in CI already knows your route architecture, module boundaries, security requirements, etc.

### Recommended FrameCast CI Workflows

**1. Auto PR Review (highest value)**
```yaml
name: Claude PR Review
on:
  pull_request:
    types: [opened, synchronize]
jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            REPO: ${{ github.repository }}
            PR NUMBER: ${{ github.event.pull_request.number }}
            Review this PR for code quality, bugs, security, and FrameCast conventions.
          claude_args: "--max-turns 5"
```

**2. Security Review on Sensitive Paths**
```yaml
on:
  pull_request:
    paths:
      - "app/modules/auth.py"
      - "app/modules/wifi.py"
      - "app/modules/updater.py"
      - "app/api.py"
      - "systemd/**"
      - "pi-gen/**"
```

**3. Issue Triage (if you open issues for yourself)**
```yaml
on:
  issues:
    types: [opened]
```

### Cost Considerations
- Each PR review consumes API tokens proportional to diff size + codebase context
- Control with `--max-turns 5` (default 10)
- Use `paths:` filters to avoid reviewing trivial changes
- GitHub Actions minutes consumed on ubuntu-latest runner
- For a solo dev doing 5-10 PRs/week: expect $5-20/month in API costs (varies with complexity)

### Hooks Integration
- Claude Code hooks (PreToolUse, PostToolUse, Stop) are local-only — they don't run in CI
- The CI action uses `claude_args` for configuration instead
- Your local hookify rules (bare-except blocking, venv-pip warnings) won't fire in CI
- Mitigation: encode critical rules in the CI prompt or in CLAUDE.md

---

## Part 3: CD / DevOps Patterns

### CD for Raspberry Pi Projects

#### Current FrameCast Approach
You already have OTA updates via GitHub Releases API with SHA256 verification and HMAC-signed rollback tags. This is solid for a single-device deployment.

#### Patterns from the Ecosystem

**SSH-based deployment (simplest):**
- GitHub Actions SSH into the Pi, pull code, restart services
- Requires the Pi to be reachable (Tailscale solves this for you)
- Pattern: `appleboy/ssh-action` or raw `ssh` with Tailscale

**Ansible for Pi provisioning:**
- Define Pi state as code (packages, configs, services)
- Run `ansible-playbook` from GitHub Actions
- Good for: reproducible setup after a fresh flash
- Your pi-gen stage already handles most of this at image-build time

**Mender OTA (heavy):**
- Full A/B partition OTA with rollback
- CI builds image → Mender server → device pulls update
- Overkill for a single device, designed for fleets

**Balena (heavier):**
- Container-based fleet management for IoT
- Docker on Pi with cloud orchestration
- Overkill for your architecture (you run native, not containerized)

#### Solo Developer Verdict on CD
Your current approach (GitHub Release → device polls → SHA256 verify → apply → health check → rollback) is the right architecture for a single-device, feature-frozen project. None of the fleet management tools add value at scale=1.

### Docker Layer Caching for pi-gen Builds

**What:** Cache Docker/QEMU layers between pi-gen builds to avoid rebuilding from scratch
- **Action:** `usimd/pi-gen-action` supports GitHub Actions cache for apt packages
- **Pattern:** `cache-from: type=gha` + `cache-to: type=gha,mode=max` with docker buildx
- **Value for FrameCast:** Medium. If your pi-gen builds are slow (they typically are — 30-60min), caching apt downloads alone can save 10-15 minutes. The pi-gen action supports this natively
- **Solo developer verdict:** Worth investigating if your pi-gen CI build time bothers you

### GitHub Environments

**What:** Named deployment targets (dev/staging/prod) with protection rules (required reviewers, wait timers, branch restrictions)
- **Limitation:** Required reviewers and wait timers only available for public repos on Free/Pro plans. Private repos need Enterprise
- **Value for FrameCast:** Low. You deploy to one Pi. There's no staging environment. The concept of "environments" implies multiple targets
- **Solo developer verdict:** Skip. Your branch protection + PR workflow already provides the gating you need

### Immutable Infrastructure / A/B Partitions

**What:** Treat the Pi image as an immutable artifact — never update in place, always flash a new image
- **A/B partition:** Two root partitions, boot from one, write updates to the other, swap on next boot
- **Tools:** OSTree (used by Fedora IoT), RAUC, Mender
- **Value for FrameCast:** Architecturally interesting but overkill. Your OTA updater with rollback achieves the same safety with less complexity. A/B partitions matter for fleet devices where you can't physically intervene
- **Solo developer verdict:** Learn about it conceptually. Don't implement it. Your current rollback mechanism is sufficient

### Supply Chain Security Beyond Cosign

**SLSA Provenance (Build Level 2-3):**
- `actions/attest-build-provenance` generates provenance attestations
- Proves "this artifact came from this commit via this workflow"
- Free for public repos, natural extension of your cosign signing
- Worth adding (see Tier 1 above)

**In-toto Attestations:**
- Framework for supply chain verification
- GitHub artifact attestations use in-toto format under the hood
- No separate action needed — `actions/attest` handles it

**GitHub Artifact Attestations:**
- Bind artifacts to SLSA predicates with Sigstore signatures
- Verifiable with `gh attestation verify`
- This is the recommended path — it wraps SLSA + in-toto + Sigstore into one GitHub-native workflow

### ChatOps (Telegram-Triggered Deployments)

**What:** `/deploy` commands in Telegram/Slack that trigger GitHub Actions
- **Pattern:** Telegram webhook → GitHub `repository_dispatch` → workflow runs
- **Value for FrameCast:** You already have Telegram notification on builds. Reverse direction (Telegram triggers deploy) is interesting but unnecessary for a feature-frozen project
- **Solo developer verdict:** Fun learning project, not needed. Your current flow (merge PR → release-please → OTA) is already automated

---

## Summary Matrix

| Integration | Value | Effort | Recommend? |
|------------|-------|--------|------------|
| **actionlint** | High | Low | Yes |
| **commitlint** | Medium-High | Low | Yes (release-please depends on it) |
| **Claude Code Action (PR review)** | High | Medium | Yes |
| **Claude Code Security Review** | High | Low | Yes (for auth/wifi/updater paths) |
| **SBOM (cdxgen)** | Medium-High | Low | Yes |
| **Artifact Attestations** | Medium-High | Low | Yes (if public repo) |
| Trivy | Moderate | Low | Maybe (install binary, skip compromised action) |
| OSSF Scorecard | Moderate | Low | Run once manually |
| harden-runner | Low-Moderate | Low | Nice-to-have |
| PR Size Labels | Low-Moderate | Low | Optional |
| Reusable Workflows | Low (single repo) | Medium | Skip for now |
| Renovate | Low | Medium | Stay with Dependabot |
| License Scanning | Low | Medium | Skip |
| Stale Bot | Low | Low | Skip |
| OpenSSF Badge | Educational | Low | Self-assess once |
| OPA/Rego | Overkill | High | Skip |
| DORA Metrics | Overkill | Medium | Skip |
| Feature Flags | Overkill | High | Skip |
| GitHub Environments | Low | Low | Skip (single device) |
| A/B Partitions | Overkill | Very High | Skip |
| ChatOps Deploy | Fun | Medium | Skip |
| Docker Layer Caching | Medium | Low | If build time bothers you |

### Recommended Implementation Order

1. **actionlint** — 15 minutes, immediate value, catches workflow bugs
2. **commitlint** — 30 minutes, protects your release-please pipeline
3. **Claude Code Action (PR review)** — 1 hour, highest ongoing value
4. **Claude Code Security Review** — 30 minutes, path-specific for sensitive modules
5. **SBOM generation** — 30 minutes, completes your supply chain story
6. **Artifact attestations** — 15 minutes, extends your cosign signing

Total estimated effort: ~3 hours for all Tier 1 items.

---

## Sources

### GitHub Actions Best Practices
- [Top 7 GitHub Actions 2025](https://dev.to/pv_vaisak/top-7-github-actions-you-should-be-using-in-2025-21i4)
- [GitHub Actions Security Best Practices](https://medium.com/@amareswer/github-actions-security-best-practices-1d3f33cdf705)
- [DevToolbox CI/CD Guide 2026](https://devtoolbox.dedyn.io/blog/github-actions-cicd-complete-guide)

### Renovate vs Dependabot
- [Renovate Bot Comparison Docs](https://docs.renovatebot.com/bot-comparison/)
- [Dependabot vs Renovate 2026 (AppSec Santa)](https://appsecsanta.com/sca-tools/dependabot-vs-renovate)
- [Why I Recommend Renovate (Jamie Tanna)](https://www.jvt.me/posts/2024/04/12/use-renovate/)

### actionlint
- [rhysd/actionlint](https://github.com/rhysd/actionlint) — 3.7k stars
- [actionlint Marketplace](https://github.com/marketplace/actions/actionlint)

### Trivy
- [aquasecurity/trivy](https://github.com/aquasecurity/trivy) — 24k+ stars
- [Trivy GitHub Actions Tag Compromise (March 2026)](https://thehackernews.com/2026/03/trivy-security-scanner-github-actions.html)
- [Socket.dev: Trivy Under Attack Again](https://socket.dev/blog/trivy-under-attack-again-github-actions-compromise)

### OSSF Scorecard
- [ossf/scorecard-action](https://github.com/ossf/scorecard-action)
- [OpenSSF Scorecard](https://scorecard.dev/)
- [GitHub Blog: Reducing Security Risk with Scorecards V4](https://github.blog/open-source/reducing-security-risk-oss-actions-opensff-scorecards-v4/)

### StepSecurity harden-runner
- [step-security/harden-runner](https://github.com/step-security/harden-runner)
- [StepSecurity Docs](https://docs.stepsecurity.io/harden-runner)

### SBOM Generation
- [cdxgen/cdxgen](https://github.com/cdxgen/cdxgen) — multi-language CycloneDX
- [CycloneDX Python SBOM Action](https://github.com/marketplace/actions/cyclonedx-python-generate-sbom)
- [OpenSSF: Choosing an SBOM Tool](https://openssf.org/blog/2025/06/05/choosing-an-sbom-generation-tool/)

### commitlint
- [conventional-changelog/commitlint](https://github.com/conventional-changelog/commitlint) — 17k+ stars
- [wagoid/commitlint-github-action](https://github.com/wagoid/commitlint-github-action)

### Claude Code CI
- [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action) — 6.4k stars, MIT
- [Claude Code GitHub Actions Docs](https://code.claude.com/docs/en/github-actions)
- [Claude Code Action Solutions Guide](https://github.com/anthropics/claude-code-action/blob/main/docs/solutions.md)
- [anthropics/claude-code-security-review](https://github.com/anthropics/claude-code-security-review)
- [Anthropic: Automate Security Reviews with Claude Code](https://www.anthropic.com/news/automate-security-reviews-with-claude-code)
- [Best AI Code Review Tools 2026](https://www.verdent.ai/guides/best-ai-for-code-review-2026)

### SLSA / Artifact Attestations
- [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance)
- [GitHub Docs: Artifact Attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- [SLSA Provenance Spec](https://slsa.dev/spec/v0.1/provenance)

### Reusable Workflows
- [GitHub Docs: Reuse Workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
- [DRY in GitHub Actions (Ultimate RnD)](https://rnd.ultimate.ai/blog/central-workflows)

### CD / IoT Deployment
- [pi-gen-action](https://github.com/usimd/pi-gen-action) — GitHub Actions for pi-gen
- [Docker Layer Caching Guide (Blacksmith)](https://www.blacksmith.sh/blog/cache-is-king-a-guide-for-docker-layer-caching-in-github-actions)
- [GitHub Docs: Deployment Environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments)
- [Mender CI/CD + Fleet Management](https://hub.mender.io/t/ci-cd-and-fleet-management-with-git-github-actions-mender-ansible-pytest-and-debian/4959)
- [Balena IoT Fleet Management](https://www.balena.io/)
- [DORA Metrics Guide](https://dora.dev/guides/dora-metrics/)
- [github-dora-metrics](https://github.com/mikaelvesavuori/github-dora-metrics)
