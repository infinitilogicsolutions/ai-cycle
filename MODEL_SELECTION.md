# Model selection in AI Cycle

Based on OpenAI and Anthropic official CLI documentation checked November 15, 2026.

## Recommended profiles

| Profile | Codex writer/spec generator | Claude spec/code reviewer | When |
| --- | --- | --- | --- |
| quality | `gpt-6.1-sol`, high reasoning | `claude-opus-5-5`, high effort | Architecture, security, data migrations, cross-service changes |
| balanced (default) | `gpt-6.1-sol`, medium reasoning | `claude-sonnet-5-5`, high effort | Routine features, regular PR delivery |
| fast | `gpt-6-luna`, medium reasoning | `claude-sonnet-5-5`, medium effort | Small low-risk implementation tasks |

Profiles merely preset CLI model flags; they do not switch models dynamically. Access varies by account, client, and rollout.

## Choose the best empirically

1. Pick 5–10 representative tasks from your repo (API changes, frontend components, tests, security checks).
2. Run the same approved PRDs with each profile in a controlled throwaway branch/worktree.
3. Compare successful test/acceptance coverage, severe human-found defects, review cycles, elapsed time, and token/cost usage where measurable.
4. Use the cheapest profile that meets your quality threshold. Escalate individual risky tasks to `quality`.
5. Change models in the private project config (`ai-cycle config` shows the location), and record model IDs per task if auditability matters.

## Limits

- Independent reviews are useful, but no model substitutes for CI/security scanning or human review.
- `--model` flags work only for model IDs your authenticated CLIs allow.
- On November 15, 2026, `gpt-6.1-sol`, `gpt-6-luna`, `claude-opus-5-5`, and `claude-sonnet-5-5` were documented choices; check official CLI model menus for changes.
- Specifications are private in your local file system, **not invisible to the providers**. Agents read/send their contents during execution.

Official sources:
- https://learn.chatgpt.com/docs/models?surface=cli
- https://learn.chatgpt.com/docs/developer-commands?surface=cli
- https://support.claude.com/en/articles/11940350-claude-code-model-configuration
- https://code.claude.com/docs/en/cli-reference