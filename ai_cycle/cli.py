"""AI Cycle: external Spec Kit workspace + Codex author + Claude reviewer.

No API client dependencies. Agents run via installed CLI commands; the user's CLI
accounts are responsible for authentication and model availability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path


class CycleError(RuntimeError):
    pass


MODEL_PROFILES = {
    "quality": {"codex_model": "gpt-6.1-sol", "claude_model": "claude-opus-5-5",
                "codex_reasoning": "high", "claude_effort": "high"},
    "balanced": {"codex_model": "gpt-6.1-sol", "claude_model": "claude-sonnet-5-5",
                 "codex_reasoning": "medium", "claude_effort": "high"},
    "fast": {"codex_model": "gpt-6-luna", "claude_model": "claude-sonnet-5-5",
             "codex_reasoning": "medium", "claude_effort": "medium"},
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9-]+", "-", value.lower().strip()).strip("-")
    if not result or len(result) > 64:
        raise CycleError("Feature must be 1–64 URL-safe characters")
    return result


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def save_json(path: Path, data: dict) -> None:
    private_dir(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def load_json(path: Path) -> dict:
    if not path.exists():
        raise CycleError(f"Missing {path}; run 'ai-cycle init' or 'ai-cycle start' first")
    return json.loads(path.read_text(encoding="utf-8"))


def exec_cmd(args: list[str], cwd: Path, *, log: Path | None = None, timeout: int = 3600,
             check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
    if not args:
        raise CycleError("Empty command")
    if shutil.which(args[0]) is None:
        raise CycleError(f"Executable '{args[0]}' is not installed or not on PATH")
    print(f"  $ {shlex.join(args[:9])}{' ...' if len(args) > 9 else ''}")
    try:
        result = subprocess.run(args, cwd=str(cwd), input=input_text, text=True,
                                capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CycleError(f"Command timed out after {timeout}s: {args[0]}") from exc
    if log:
        private_dir(log.parent)
        log.write_text(f"COMMAND: {shlex.join(args[:9])}\nEXIT: {result.returncode}\n"
                       f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n", encoding="utf-8")
        if os.name != "nt":
            log.chmod(0o600)
    if check and result.returncode:
        tail = (result.stderr or result.stdout)[-1200:]
        raise CycleError(f"Command failed ({result.returncode}): {args[0]}\n{tail}\n"
                         + (f"Full log: {log}" if log else ""))
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    return exec_cmd(["git", *args], repo, check=check).stdout.strip()


def require_clean_repo(repo: Path) -> None:
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise CycleError("Repository has uncommitted/untracked changes. Commit or stash them first.")


def workspace_root(repo: Path) -> Path:
    base = Path(os.environ.get("AI_CYCLE_HOME", "~/.ai-cycle")).expanduser().resolve()
    marker = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:10]
    candidate = base / "projects" / f"{slug(repo.name)}-{marker}"
    if repo.resolve() == candidate or repo.resolve() in candidate.parents:
        raise CycleError("AI_CYCLE_HOME would put private specs inside the application repository")
    return private_dir(candidate)


def feature_root(repo: Path, feature: str) -> Path:
    return workspace_root(repo) / "features" / slug(feature)


def get_config(repo: Path) -> dict:
    config = load_json(workspace_root(repo) / "config.json")
    if Path(config["repo"]).resolve() != repo.resolve():
        raise CycleError("Config repository path mismatch")
    return config


def get_state(repo: Path, feature: str) -> tuple[Path, dict]:
    folder = feature_root(repo, feature)
    return folder, load_json(folder / "state.json")


def write_state(folder: Path, state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(folder / "state.json", state)


def ensure_prd_unchanged(folder: Path, state: dict) -> None:
    if digest((folder / "prd.md").read_bytes()) != state["approved_prd_hash"]:
        raise CycleError("Approved PRD changed. Create a new feature or explicitly reapprove.")


def guard_stage_names(paths: list[str]) -> None:
    """Fail closed on private artifact or credential-like paths before publishing."""
    banned_names = {"spec.md", "plan.md", "tasks.md", "prd.md", "reviews.md"}
    banned_parts = {".specify", ".ai-cycle", "specs", "reviews", ".env", ".ssh", ".aws"}
    for path in paths:
        parts = Path(path).parts
        lower = [part.lower() for part in parts]
        filename = lower[-1] if lower else ""
        if (filename in banned_names or any(p in banned_parts for p in lower)
            or filename.startswith(".env") or filename.endswith((".pem", ".key", ".p12", ".pfx"))):
            raise CycleError(f"Refusing to include private/spec/credential file in PR: {path}")


def setup_repo(repo: Path, args) -> None:
    if not (repo / ".git").exists() and not git(repo, "rev-parse", "--is-inside-work-tree", check=False) == "true":
        raise CycleError("Project must be a Git repository")
    config_path = workspace_root(repo) / "config.json"
    if config_path.exists() and not args.force:
        raise CycleError("Already initialized. Use 'ai-cycle config' to view, or --force to replace.")
    models = dict(MODEL_PROFILES[args.profile])
    for key in ("codex_model", "claude_model", "codex_reasoning", "claude_effort"):
        override = getattr(args, key, None)
        if override is not None:
            models[key] = override
    config = {
        "repo": str(repo), "base_branch": args.base, "build": args.build,
        "test": args.test, "model_profile": args.profile, **models,
        "max_review_cycles": args.max_cycles,
        "spec_engine": "speckit", "require_prd_approval": True,
        "require_human_merge": True,
    }
    save_json(config_path, config)
    print(f"Initialized: {repo}\nPrivate config: {config_path}")
    print("No files were added to the application repository.")


def start(repo: Path, args) -> None:
    get_config(repo)
    folder = feature_root(repo, args.feature)
    if (folder / "state.json").exists():
        raise CycleError("Feature already exists; use another name")
    source = Path(args.prd).expanduser().resolve()
    content = source.read_bytes()
    if not content.strip():
        raise CycleError("PRD is empty")
    private_dir(folder)
    target = folder / "prd.md"
    target.write_bytes(content)
    if os.name != "nt":
        target.chmod(0o600)
    state = {"feature": slug(args.feature), "phase": "awaiting_prd_approval",
             "prd_sha256": digest(content), "approved_prd_hash": None,
             "review_cycles": 0, "spec_review_cycles": 0}
    write_state(folder, state)
    print(f"PRD copied into PRIVATE workspace: {target}")
    print(f"SHA-256: {state['prd_sha256']}")
    print(f"Approve after reading it: ai-cycle --repo {shlex.quote(str(repo))} approve {slug(args.feature)} prd")


def approve(repo: Path, args) -> None:
    folder, state = get_state(repo, args.feature)
    if args.stage == "prd":
        if state["phase"] != "awaiting_prd_approval":
            raise CycleError("PRD is not awaiting approval")
        current_hash = digest((folder / "prd.md").read_bytes())
        print(f"Approved document candidate: {folder / 'prd.md'}\nSHA-256: {current_hash}")
        if args.yes:
            # Explicit --yes is an intentional approval, useful for scripts with a human gate.
            pass
        else:
            answer = input("Have you read and approved this exact PRD? Type APPROVE: ")
            if answer != "APPROVE":
                raise CycleError("Approval cancelled")
        state["approved_prd_hash"] = current_hash
        state["phase"] = "prd_approved"
    elif args.stage == "design":
        if state["phase"] != "awaiting_design_approval":
            raise CycleError("No architecture decision is awaiting approval")
        if not args.note or len(args.note.strip()) < 6:
            raise CycleError("Provide --note with the approved architecture decision")
        (folder / "design-approval.md").write_text(args.note.strip() + "\n", encoding="utf-8")
        state.pop("resume_after_design", None)
        state["phase"] = "design_approved_pending_spec_review"
    else:
        raise CycleError("Unknown approval stage")
    write_state(folder, state)
    print(f"Approved {args.stage}; next: ai-cycle run {state['feature']}")


def codex(repo: Path, cwd: Path, cfg: dict, prompt: str, log: Path,
          *, add_dir: Path | None = None) -> None:
    cmd = ["codex", "exec", "--cd", str(cwd), "--sandbox", "workspace-write",
           "--ask-for-approval", "never", "--model", cfg["codex_model"],
           "-c", f"model_reasoning_effort={json.dumps(cfg['codex_reasoning'])}"]
    if add_dir:
        cmd += ["--skip-git-repo-check", "--add-dir", str(add_dir)]
    cmd.append(prompt)
    exec_cmd(cmd, cwd, log=log, timeout=7200)


REVIEW_SCHEMA = {"type": "object", "properties": {
    "approved": {"type": "boolean"},
    "requires_human_decision": {"type": "boolean"},
    "findings": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"}},
    "required": ["approved", "requires_human_decision", "findings", "summary"],
    "additionalProperties": False}


def claude_review(repo: Path, cfg: dict, prompt: str, log: Path) -> dict:
    cmd = ["claude", "-p", "--safe-mode", "--model", cfg["claude_model"],
           "--effort", cfg["claude_effort"], "--tools", "Read,Glob,Grep",
           "--disallowedTools", "mcp__*", "--permission-prompts", "none",
           "--add-dir", str(log.parent.parent), "--output-format", "json", "--json-schema", json.dumps(REVIEW_SCHEMA),
           "--no-session-persistence", prompt]
    result = exec_cmd(cmd, repo, log=log, timeout=3600)
    try:
        payload = json.loads(result.stdout)
        outcome = payload["structured_output"]
        assert all(key in outcome for key in REVIEW_SCHEMA["required"])
        assert isinstance(outcome["approved"], bool)
        assert isinstance(outcome["requires_human_decision"], bool)
        assert isinstance(outcome["findings"], list)
        return outcome
    except (ValueError, AssertionError, KeyError, TypeError) as exc:
        raise CycleError(f"Claude did not produce valid structured review output: {log}") from exc


def speckit_init(repo: Path, folder: Path) -> Path:
    workspace = private_dir(folder / "spec-kit")
    if not (workspace / ".specify").exists():
        exec_cmd(["specify", "init", "--here", "--force", "--non-interactive",
                  "--integration", "codex", "--integration-options=--skills"],
                 workspace, log=folder / "logs" / "speckit-init.log", timeout=600)
    (workspace / "APPROVED_PRD.md").write_bytes((folder / "prd.md").read_bytes())
    return workspace


def locate_specs(workspace: Path) -> tuple[Path, Path, Path]:
    candidates = list((workspace / "specs").glob("*/spec.md"))
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    for spec in candidates:
        plan, tasks = spec.parent / "plan.md", spec.parent / "tasks.md"
        if plan.is_file() and tasks.is_file() and all(p.stat().st_size > 80 for p in (spec, plan, tasks)):
            return spec, plan, tasks
    raise CycleError("Spec Kit did not produce complete specs/*/{spec,plan,tasks}.md; inspect logs")


def check_spec_integrity(repo: Path, start_status: str) -> None:
    if git(repo, "status", "--porcelain", "--untracked-files=all") != start_status:
        raise CycleError("Codex changed the application repository during spec generation. "
                         "Do not proceed; review and restore changes manually.")


def make_specs(repo: Path, folder: Path, state: dict, cfg: dict) -> None:
    ensure_prd_unchanged(folder, state)
    require_clean_repo(repo)
    original_status = git(repo, "status", "--porcelain", "--untracked-files=all")
    workspace = speckit_init(repo, folder)
    state["phase"] = "spec_generation"
    write_state(folder, state)
    instructions = (f"Approved PRD: {workspace / 'APPROVED_PRD.md'}; existing application source: {repo}. "
                    "Treat approved PRD as immutable. Inspect application architecture. "
                    "Run Spec Kit skill for this phase in the current PRIVATE Spec Kit workspace, "
                    "not in the application repository. All spec outputs must remain in this private workspace. "
                    "Never write any file in the application repository. Do not commit, push, or create PRs. "
                    "If clarification materially changes requirements, surface it as an open question.")
    for number, (skill, title) in enumerate([
        ("$speckit-specify", "functional specification"),
        ("$speckit-plan", "implementation architecture and plan"),
        ("$speckit-tasks", "actionable tasks and acceptance tests")], 1):
        codex(repo, workspace, cfg, f"Invoke {skill}. Generate {title}. {instructions}",
              folder / "logs" / f"{number}-spec-{title.split()[0]}.log", add_dir=repo)
        check_spec_integrity(repo, original_status)
    review_specs(repo, folder, state, cfg, workspace, original_status)


def review_specs(repo: Path, folder: Path, state: dict, cfg: dict,
                 workspace: Path, original_status: str) -> None:
    spec, plan, tasks = locate_specs(workspace)
    state["spec_paths"] = [str(p) for p in (spec, plan, tasks)]
    write_state(folder, state)
    for attempt in range(1, cfg["max_review_cycles"] + 1):
        state["spec_review_cycles"] = attempt
        write_state(folder, state)
        prompt = (f"You are the independent architect reviewing PRIVATE Spec Kit artifacts. "
                  f"Approved PRD: {folder / 'prd.md'}. App repo: {repo}. "
                  f"Human design decision: {((folder / 'design-approval.md').read_text() if (folder / 'design-approval.md').exists() else 'none')}. "
                  f"Functional spec: {spec}; Plan: {plan}; Tasks: {tasks}. "
                  "READ those files and check traceability, practicality with the existing code, "
                  "testability, security, architecture, migrations, performance, compatibility and missing requirements. "
                  "You must be strict: approved=true only with NO blocking findings. "
                  "If any architecture trade-off or PRD ambiguity needs an owner's decision, "
                  "requires_human_decision=true. Do not edit anything.")
        verdict = claude_review(repo, cfg, prompt, folder / "reviews" / f"spec-{attempt}.log")
        save_json(folder / "reviews" / f"spec-{attempt}.json", verdict)
        if verdict["requires_human_decision"]:
            state["phase"] = "awaiting_design_approval"
            write_state(folder, state)
            print("Design decision required. Inspect the latest spec review; approve with a decision note.")
            return
        if verdict["approved"] and not verdict["findings"]:
            state["phase"] = "specs_approved"
            state["spec_paths"] = [str(p) for p in (spec, plan, tasks)]
            write_state(folder, state)
            return
        if attempt < cfg["max_review_cycles"]:
            codex(repo, workspace, cfg,
                  f"Fix ONLY the PRIVATE spec artifacts {spec}, {plan}, {tasks} in response to "
                  f"independent review findings: {json.dumps(verdict['findings'])}. "
                  "Do not change app code or approved PRD. Keep consistent Spec Kit artifacts.",
                  folder / "logs" / f"spec-repair-{attempt}.log", add_dir=repo)
            check_spec_integrity(repo, original_status)
    state["phase"] = "blocked_spec_review"
    write_state(folder, state)
    raise CycleError("Spec review did not pass within max cycles; see private reviews")



def repair_after_design_approval(repo: Path, folder: Path, state: dict, cfg: dict) -> None:
    """Human design approval is NOT a bypass for independent spec re-review."""
    ensure_prd_unchanged(folder, state)
    workspace = folder / "spec-kit"
    if not workspace.is_dir() or "spec_paths" not in state:
        raise CycleError("Missing private spec workspace to revise after design decision")
    original_status = git(repo, "status", "--porcelain", "--untracked-files=all")
    approved_decision = (folder / "design-approval.md").read_text(encoding="utf-8")
    codex(repo, workspace, cfg,
          f"Update private Spec Kit spec, plan, and tasks at {state['spec_paths']} "
          f"to incorporate this HUMAN APPROVED decision: {approved_decision}. "
          "Maintain compatibility with the locked PRD. Do not modify the application repository. "
          "No code changes, git operations, commits or pushes.",
          folder / "logs" / "design-revision.log", add_dir=repo)
    check_spec_integrity(repo, original_status)
    review_specs(repo, folder, state, cfg, workspace, original_status)


def make_branch(repo: Path, state: dict, cfg: dict) -> None:
    branch = f"ai/{state['feature']}"
    current = git(repo, "branch", "--show-current")
    if current == branch:
        return
    if current != cfg["base_branch"]:
        raise CycleError(f"Switch to base branch '{cfg['base_branch']}' before implementation (current: {current})")
    require_clean_repo(repo)
    if git(repo, "branch", "--list", branch):
        raise CycleError(f"Branch already exists: {branch}. Switch to it and rerun")
    git(repo, "switch", "-c", branch)


def run_project_command(repo: Path, command: str | None, folder: Path, name: str, attempt: int) -> tuple[bool, str]:
    if not command:
        return True, f"{name}: not configured; MANUAL VALIDATION REQUIRED"
    log = folder / "checks" / f"{name}-{attempt}.log"
    # Only trusted user-supplied config commands are executed, never model output.
    result = exec_cmd(["sh", "-c", command], repo, log=log, timeout=1800, check=False)
    return result.returncode == 0, f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}; log {log}"


def code_review(repo: Path, folder: Path, state: dict, cfg: dict, attempt: int, checks: list[str]) -> dict:
    # Claude has no shell/Bash tool. Export the actual Git diff into the PRIVATE
    # workspace so independent read-only review can inspect every tracked change.
    patch_text = git(repo, "diff", "--no-ext-diff", "--binary", cfg["base_branch"])
    patch_path = folder / "reviews" / f"code-{attempt}.patch"
    private_dir(patch_path.parent)
    patch_path.write_text(patch_text + "\n", encoding="utf-8")
    if os.name != "nt":
        patch_path.chmod(0o600)
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    # Do not treat untracked new files as reviewed merely because git diff omitted them.
    prompt = (f"Review feature {state['feature']} as an independent reviewer. "
              f"APPROVED PRD {folder / 'prd.md'}; SPEC {', '.join(state['spec_paths'])}; "
              f"code repository {repo}; base branch {cfg['base_branch']}. "
              f"Read PRIVATE git patch {patch_path} against base AND these UNTRACKED implementation files: {json.dumps(untracked)}. "
              "Read relevant code and tests, assess security, logic, regression, error handling, "
              "PRD/spec traceability, and missing tests. Do not modify any file. "
              f"Build/test results: {json.dumps(checks)}. "
              "Be strict: approved=true only if code and configured checks pass, "
              "with no blocking findings. No auto-merge or publish.")
    verdict = claude_review(repo, cfg, prompt, folder / "reviews" / f"code-{attempt}.log")
    save_json(folder / "reviews" / f"code-{attempt}.json", verdict)
    return verdict


def implement(repo: Path, folder: Path, state: dict, cfg: dict) -> None:
    ensure_prd_unchanged(folder, state)
    make_branch(repo, state, cfg)
    state["phase"] = "implementing"
    write_state(folder, state)
    for attempt in range(1, cfg["max_review_cycles"] + 1):
        state["review_cycles"] = attempt
        write_state(folder, state)
        prior_findings = None
        if attempt > 1:
            prior = load_json(folder / "reviews" / f"code-{attempt - 1}.json")
            prior_findings = prior["findings"]
        prompt = (f"Implement approved feature {state['feature']}. APPLICATION REPO: {repo}. "
                  f"Approved PRD: {folder / 'prd.md'}. "
                  f"Spec, plan and tasks: {', '.join(state['spec_paths'])}. "
                  "Read those approved PRIVATE artifacts, follow AGENTS.md and existing project patterns. "
                  "Write application code and tests ONLY inside the application repo. "
                  "Do NOT copy any specs, plans, PRDs, agent review logs, or credentials into repo. "
                  "Do not commit, push, change git branches, open PRs, or modify the approved PRD. "
                  "Implement tasks with tests. ")
        if prior_findings is not None:
            prompt += f"Fix independent review findings: {json.dumps(prior_findings)}. "
        codex(repo, repo, cfg, prompt, folder / "logs" / f"implement-{attempt}.log")
        changed_files = git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
        if not changed_files:
            raise CycleError("Codex made no application changes")
        paths = [line[3:] for line in changed_files if len(line) >= 4]
        guard_stage_names(paths)
        checks = [run_project_command(repo, cfg.get("build"), folder, "build", attempt),
                  run_project_command(repo, cfg.get("test"), folder, "test", attempt)]
        details = [text for _, text in checks]
        verdict = code_review(repo, folder, state, cfg, attempt, details)
        if verdict["requires_human_decision"]:
            state["phase"] = "awaiting_design_approval"
            write_state(folder, state)
            return
        if all(ok for ok, _ in checks) and all(cfg.get(x) for x in ("build", "test")) \
                and verdict["approved"] and not verdict["findings"]:
            state["phase"] = "ready_for_pr"
            write_state(folder, state)
            print("Code passes configured checks and independent review. Ready for DRAFT PR.")
            return
        # If tests fail but Claude missed them, codify failure for repair.
        if attempt < cfg["max_review_cycles"]:
            findings = verdict["findings"] + [msg for ok, msg in checks if not ok]
            verdict["findings"] = findings
            save_json(folder / "reviews" / f"code-{attempt}.json", verdict)
    state["phase"] = "blocked_code_review"
    write_state(folder, state)
    raise CycleError("Implementation did not pass review/tests within max cycles")


def run(repo: Path, args) -> None:
    cfg = get_config(repo)
    folder, state = get_state(repo, args.feature)
    if state["phase"] == "awaiting_prd_approval":
        raise CycleError("PRD not yet approved")
    if state["phase"] in ("prd_approved", "spec_generation"):
        make_specs(repo, folder, state, cfg)
        state = load_json(folder / "state.json")
    if state["phase"] == "design_approved_pending_spec_review":
        repair_after_design_approval(repo, folder, state, cfg)
        state = load_json(folder / "state.json")
    if state["phase"] == "specs_approved":
        implement(repo, folder, state, cfg)
        return
    if state["phase"] in ("ready_for_pr", "draft_pr_opened"):
        print(f"Already {state['phase']}")
        return
    if state["phase"] == "awaiting_design_approval":
        print("Review required: see private spec/code review and approve design with --note.")
        return
    raise CycleError(f"Phase '{state['phase']}' requires manual intervention; see private logs")


def publish(repo: Path, args) -> None:
    cfg = get_config(repo)
    folder, state = get_state(repo, args.feature)
    if state["phase"] != "ready_for_pr":
        raise CycleError("PR requires a successful review and test run")
    if git(repo, "branch", "--show-current") != f"ai/{state['feature']}":
        raise CycleError("Expected feature branch is not currently checked out")
    if not args.yes:
        raise CycleError("Use '--yes' to explicitly authorize commit, push, and remote DRAFT PR creation")
    # Do not stage until filenames are inspected. Staged files are inspected again.
    change_lines = git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    paths = [line[3:] for line in change_lines if len(line) >= 4]
    guard_stage_names(paths)
    if not paths:
        raise CycleError("Nothing to publish")
    for path in paths:
        candidate = repo / path
        if candidate.is_symlink():
            raise CycleError(f"Symlink requires manual publishing: {path}")
        if candidate.is_file() and candidate.stat().st_size > 5_000_000:
            raise CycleError(f"Large file requires manual publishing: {path}")
    git(repo, "add", "--all")
    staged = git(repo, "diff", "--cached", "--name-only").splitlines()
    guard_stage_names(staged)
    git(repo, "commit", "-m", f"feat: {state['feature']}")
    git(repo, "push", "--set-upstream", "origin", f"ai/{state['feature']}")
    body = folder / "pr-body.md"
    body.write_text(f"## Feature\n{state['feature']}\n\n"
                    "## Delivery\n- Approved PRD and private Spec Kit artifacts used\n"
                    "- Codex implementation, independent Claude review\n"
                    "- Build and tests passed\n\n"
                    "The PRD, specs, task plan and review logs are intentionally excluded.\n"
                    "Human review and approval required before merge.\n", encoding="utf-8")
    result = exec_cmd(["gh", "pr", "create", "--draft", "--base", cfg["base_branch"],
                       "--title", f"feat: {state['feature']}", "--body-file", str(body)],
                      repo, log=folder / "logs" / "publish.log", timeout=120)
    state["phase"] = "draft_pr_opened"
    state["pr_url"] = result.stdout.strip()
    write_state(folder, state)
    print(f"Draft PR: {result.stdout.strip()}")


def doctor(repo: Path) -> None:
    print("AI Cycle dependency check")
    for cmd in ("git", "codex", "claude", "specify", "gh"):
        print(f"  {cmd:8} {'FOUND: ' + str(shutil.which(cmd)) if shutil.which(cmd) else 'MISSING'}")
    print("CLI login is required separately for Codex, Claude Code, and GitHub.")
    cfg_path = workspace_root(repo) / "config.json"
    print(f"  config: {'FOUND' if cfg_path.exists() else 'not initialized'} {cfg_path}")



def show(repo: Path, feature: str, artifact: str) -> None:
    """Read artifacts from the private workspace without changing Git or approvals."""
    folder, state = get_state(repo, feature)
    if artifact == "prd":
        target = folder / "prd.md"
    elif artifact == "review":
        candidates = list((folder / "reviews").glob("spec-*.json")) + \
                     list((folder / "reviews").glob("code-*.json"))
        if not candidates:
            raise CycleError("No Claude review report exists for this feature yet")
        target = max(candidates, key=lambda item: item.stat().st_mtime_ns)
    elif artifact in {"spec", "plan", "tasks"}:
        paths = state.get("spec_paths", [])
        if len(paths) != 3:
            raise CycleError("No complete approved/generated specification exists yet")
        target = Path(paths[{"spec": 0, "plan": 1, "tasks": 2}[artifact]])
        # Only allow previously recorded artifacts in this feature's private workspace.
        if not target.resolve().is_relative_to(folder.resolve()):
            raise CycleError("Specification path is outside the private feature workspace")
    else:
        raise CycleError(f"Unknown artifact: {artifact}")
    if not target.is_file():
        raise CycleError(f"Artifact not found: {target}")
    print(f"PRIVATE artifact: {target}\n")
    print(target.read_text(encoding="utf-8"))


def guide(open_browser: bool = True) -> None:
    """Open the packaged, entirely offline step-by-step command wizard."""
    page = Path(__file__).resolve().parent / "web" / "guide.html"
    if not page.is_file():
        raise CycleError("Wizard UI was not included in this installation")
    url = page.as_uri()
    print(f"AI Cycle guided setup: {url}")
    if open_browser:
        if not webbrowser.open(url):
            print("Browser did not open automatically; copy the file URL above into it")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-cycle", description=__doc__)
    p.add_argument("--repo", default=".", help="Application Git repository (default current directory)")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Configure this repo outside Git")
    init.add_argument("--base", default="main")
    init.add_argument("--build", default=None, help="Trusted shell command")
    init.add_argument("--test", default=None, help="Trusted shell command")
    init.add_argument("--profile", choices=tuple(MODEL_PROFILES), default="balanced")
    init.add_argument("--codex-model", default=None)
    init.add_argument("--claude-model", default=None)
    init.add_argument("--codex-reasoning", choices=["low", "medium", "high", "xhigh"], default=None)
    init.add_argument("--claude-effort", choices=["low", "medium", "high", "xhigh"], default=None)
    init.add_argument("--max-cycles", type=int, choices=range(1, 6), metavar="1..5", default=3)
    init.add_argument("--force", action="store_true")
    start_p = sub.add_parser("start", help="Import a PRD without starting coding")
    start_p.add_argument("feature")
    start_p.add_argument("--prd", required=True)
    approve_p = sub.add_parser("approve", help="Explicit human PRD or design approval")
    approve_p.add_argument("feature")
    approve_p.add_argument("stage", choices=["prd", "design"])
    approve_p.add_argument("--yes", action="store_true", help="Noninteractive explicit approval")
    approve_p.add_argument("--note", help="Required for design approvals")
    run_p = sub.add_parser("run", help="Run private Spec Kit → review → implementation loop")
    run_p.add_argument("feature")
    pub = sub.add_parser("pr", help="Explicitly commit, push and create DRAFT pull request")
    pub.add_argument("feature")
    pub.add_argument("--yes", action="store_true")
    status = sub.add_parser("status", help="Show private feature state")
    status.add_argument("feature")
    sub.add_parser("doctor")
    sub.add_parser("config")
    show_p = sub.add_parser("show", help="Display the exact private PRD, a spec, or latest review")
    show_p.add_argument("feature")
    show_p.add_argument("artifact", choices=["prd", "spec", "plan", "tasks", "review"])
    guide_p = sub.add_parser("guide", help="Open the offline, step-by-step terminal wizard")
    guide_p.add_argument("--no-open", action="store_true", help="Print local file URL without opening browser")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        repo = Path(args.repo).expanduser().resolve()
        if args.command == "init": setup_repo(repo, args)
        elif args.command == "start": start(repo, args)
        elif args.command == "approve": approve(repo, args)
        elif args.command == "run": run(repo, args)
        elif args.command == "pr": publish(repo, args)
        elif args.command == "doctor": doctor(repo)
        elif args.command == "show": show(repo, args.feature, args.artifact)
        elif args.command == "guide": guide(open_browser=not args.no_open)
        elif args.command == "config": print(json.dumps(get_config(repo), indent=2))
        elif args.command == "status":
            folder, state = get_state(repo, args.feature)
            print(json.dumps(state, indent=2))
            print(f"Private workspace: {folder}")
        return 0
    except (CycleError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
