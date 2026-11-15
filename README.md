# AI Cycle — private Spec Kit + Codex + Claude orchestrator

A reusable command-line starter for **PRD approval → Spec Kit specification → Claude spec review → Codex implementation → tests → Claude code review → human-approved draft PR**.

**Status:** v0.2 guided starter. Unit-tested locally; **real Codex / Claude / Spec Kit CLI interoperability has not been exercised in this environment**. The first live project may need prompt/CLI adjustments as those tools evolve. This is not a hosted service. For public GitHub publishing, see `PUBLISHING.md`.

## Safety and scope

- **Never puts generated PRD/spec.md/plan.md/tasks.md/review logs into the application Git tree.** They live under `~/.ai-cycle/projects/<repo>-<hash>/features/<feature>/` (customizable via `AI_CYCLE_HOME`).
- Only the human can approve a PRD, and it is SHA-256 locked against subsequent changes.
- Codex produces functional spec, technical plan and tasks via **official GitHub Spec Kit skills** inside an isolated **private** Spec Kit directory. Claude reviews the generated artifacts in read-only mode.
- Codex modifies the application repo only in the implementation phase. Claude's review tools are restricted to file reads. The script verifies repo cleanliness before and after specs.
- Build and test commands are supplied per-repo. **No PR is marked ready unless both commands are configured, pass and Claude approves.**
- Up to three review cycles by default. Human architecture decisions pause the workflow.
- No automatic merge. `pr` is opt-in, creates a **draft** PR, and requires `--yes`.
- No automatic staging, commits or pushes during `run`. `pr --yes` intentionally runs `git add --all`, `commit`, `push`, and `gh pr create`; review your diff first. Guards reject spec artifacts, likely credential paths, symlinks and large files but **are not a substitute for secret scanning**.
- CLI agent tools can execute model-chosen code; run only on trusted repositories, preferably with least-privilege credentials in a container or isolated development machine. Inspect external tools, hooks, and CI configuration before using.

## Prerequisites (macOS/Linux/WSL)

1. Python 3.10+, Git, and GitHub CLI (`gh`) if you want draft-PR publishing.
2. Codex CLI installed and authenticated (`codex`), with access to your chosen model.
3. Claude Code CLI installed and authenticated (`claude`), with access to your chosen model.
4. GitHub Spec Kit CLI installed (`specify`) via its official install instructions. For example, `uv tool install specify-cli` where available; use `specify version` to verify.
5. A Git application repo with a clean working tree, an existing base branch (default `main`), configured git author identity and a GitHub `origin` remote if you want publishing.

Official references:
- OpenAI Codex CLI: https://learn.chatgpt.com/docs/non-interactive-mode
- Codex model choices: https://learn.chatgpt.com/docs/models?surface=cli
- Claude Code CLI: https://code.claude.com/docs/en/cli-reference
- Claude model configuration: https://support.claude.com/en/articles/11940350-claude-code-model-configuration
- Spec Kit: https://github.github.com/spec-kit/quickstart

## Offline guided UI (new)

You can skip memorizing the command sequence. **Open `START-HERE.html` in your browser** directly from the extracted ZIP folder (double-click on macOS), even **before installing the CLI**. No backend, API key, server or network is required for the guide itself.

The UI asks for your project location, PRD path, build and test commands, base branch, and model profile, then shows **exactly one terminal command per step**. Copy the command, run it in your terminal, verify its output, and click **I ran this successfully**. It includes an optional detour for Claude's architectural-review gates, a manual approval checkbox before PRD approval, and another before publishing.

Once installed, you can also open the guide from any directory:

```bash
ai-cycle guide
```

Or obtain a link to the packaged file without opening a browser:

```bash
ai-cycle guide --no-open
```

The guide runs entirely in your browser, stores only paths/step state locally and **does not execute commands**. It cannot verify terminal output or access your repository. The CLI below still performs the actual agent orchestration, and Codex/Claude may communicate with their model providers.

## Install

```bash
unzip ai-cycle-kit.zip
cd ai-cycle-kit
python3 -m pip install --user -e .
ai-cycle --repo /path/to/your/app doctor
```

If `ai-cycle` is not on your PATH, use `python3 -m ai_cycle.cli` from this package directory, or activate a Python virtual environment and `pip install -e .` inside it.

## Configure a repository once

```bash
ai-cycle --repo ~/code/my-dotnet-app init \
  --base main \
  --profile quality \
  --build 'dotnet build' \
  --test 'dotnet test' \
  --codex-model gpt-6.1-sol \
  --claude-model claude-opus-5-5 \
  --max-cycles 3
```

For a React/TypeScript repo: `--build 'npm run build' --test 'npm test -- --runInBand'`, adjusting to the project's real test command.

**Important:** `--build` and `--test` are trusted shell commands specified by you. The CLI does not infer or invent tests, and it does not evaluate commands produced by the agents.

Read the exact private, imported PRD before approving it:

```bash
ai-cycle --repo ~/code/my-dotnet-app show payment-wallet prd
```

If a design decision is required, inspect Claude's latest structured review:

```bash
ai-cycle --repo ~/code/my-dotnet-app show payment-wallet review
```

Once created, the spec, plan and task artifacts can also be viewed with `show payment-wallet spec`, `show payment-wallet plan`, and `show payment-wallet tasks`.

## Use for each feature

```bash
# 1) Start, copy PRD to the private store; no models called
ai-cycle --repo ~/code/my-dotnet-app start payment-wallet --prd ~/drafts/payment-wallet.md

# 2) Read and explicitly approve the PRD
ai-cycle --repo ~/code/my-dotnet-app approve payment-wallet prd

# 3) Generate actual private Spec Kit specs, review, implement, test, review
ai-cycle --repo ~/code/my-dotnet-app run payment-wallet

# 4) Check progress and private reports
ai-cycle --repo ~/code/my-dotnet-app status payment-wallet

# 5) Inspect application changes before publishing
git -C ~/code/my-dotnet-app diff
git -C ~/code/my-dotnet-app status

# 6) Explicitly authorize draft PR publication
ai-cycle --repo ~/code/my-dotnet-app pr payment-wallet --yes
```

The internal Spec Kit work area is created only during `run`, at `~/.ai-cycle/projects/.../features/payment-wallet/spec-kit/`, using:

```bash
specify init --here --force --non-interactive --integration codex --integration-options=--skills
```

Then Codex is asked to invoke `$speckit-specify`, `$speckit-plan`, and `$speckit-tasks` (official Spec Kit agent skills). Each writes into that **private** workspace, not the application repo. The implementation worker reads the approved artifacts by absolute path and writes code in the Git repo. It uses `codex exec --sandbox workspace-write` and passes the project and workspace context. Do not run this on an untrusted repository with privileged credentials.

If Claude flags an architectural decision for your approval, read the latest `reviews/spec-*.json`, then run:

```bash
ai-cycle --repo ~/code/my-dotnet-app approve payment-wallet design \
  --note 'Approved: use existing Wallet API and add backward-compatible field'
ai-cycle --repo ~/code/my-dotnet-app run payment-wallet
```

## Models — recommended settings

| Phase | Recommended model | Why |
|---|---|---|
| Complex specs + code | `gpt-6.1-sol` | Strong current Codex model for agentic engineering work |
| High-stakes architecture or security reviews | `claude-opus-5-5` | Deep review; typically more resource-intensive |
| Routine code reviews | `claude-sonnet-5-5` | Good speed/cost tradeoff |
| Small focused coding tasks | `gpt-6-luna` | Lower-cost/faster option where available |

The CLI selects Codex via `--model` and Claude via `--model`. It also passes `model_reasoning_effort=high` for Codex (configurable) and `--effort high` for Claude (configurable). Models and entitlements may change; confirm actual availability with `/model` inside the interactive `codex` and `claude` CLIs. **Avoid using an "auto" selector for reproducible approved feature work**; record explicit model IDs with the project.

There are three **explicit model profiles** (not automatic routing):

```bash
# Strongest review-oriented settings for important changes
ai-cycle init --profile quality --build 'dotnet build' --test 'dotnet test'

# Balanced is the default; Sol writing + Sonnet reviewing
ai-cycle init --profile balanced --build 'dotnet build' --test 'dotnet test'

# Fast is for simpler, low-risk tickets
ai-cycle init --profile fast --build 'dotnet build' --test 'dotnet test'
```

Supply `--codex-model`, `--claude-model`, `--codex-reasoning`, or `--claude-effort` to override a preset at initialization. Choose based on measured acceptance-test pass rate and human review findings, not benchmarks alone.

To switch the reviewer model after initialization, edit the private file shown by `ai-cycle config`, changing `claude_model` to `claude-sonnet-5-5` or `claude-opus-5-5`. Re-running `init --force` resets the configuration but does not delete feature state.

## Troubleshooting

- `specify` missing: install Spec Kit, check `specify version`.
- `$speckit-*` did not write artifacts: inspect `logs/1-spec-functional.log` etc. The actual installed Spec Kit version might use a different integration/skill name. Reconcile in the private workspace; no repo edits are made intentionally during generation.
- `Claude` no structured output: inspect private `reviews/*.log` and authentication/model availability. Claude returns its verdict in the `structured_output` JSON field; missing verdict fails closed.
- `Codex` refuses sandbox/add-dir: verify current Codex CLI flags and local sandbox configuration. The script never requests full machine access.
- `run` stops at a design gate: review private findings; use `approve ... design --note` before rerunning.
- `run` stops after max cycles: blocked state prevents unreviewed publishing. Examine logs and resolve manually.
- `gh pr create` fails: confirm GitHub login, remote permissions, base branch and branch push. The feature remains in `ready_for_pr` so you can retry after repair.

## What this starter does NOT do

It does not automatically deploy, auto-merge, import your existing repo conventions, infer build/test commands, or manage multi-repo features as one transaction. It is a local CLI starter and not a fully battle-tested CI service. PRD/spec output is private locally **but still sent to the selected model providers when those agents process it**. Local secrecy is not the same as offline processing.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Public GitHub repository publishing

Review `PUBLISHING.md`, then run `./publish.sh` from a clean extracted folder after authenticating with `gh`. The script runs tests, shows exactly which source files it will publish, and requires confirmation before creating the public repository.