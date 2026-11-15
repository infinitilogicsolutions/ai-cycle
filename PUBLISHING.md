# Publish this project to GitHub

**Suggested repository:** `infinitilogicsolutions/ai-cycle` (public).

Publishing has **not** been performed from this bundle. The ChatGPT GitHub connection used to prepare it can update existing repositories but cannot create repositories.

## Publish in one local command

On macOS, install [GitHub CLI](https://cli.github.com/) (e.g., `brew install gh`) and authenticate using `gh auth login`. Then run from this extracted folder:

```bash
./publish.sh
```

The script tests the project, stages only known source files, lists what will be public, asks for confirmation, creates `infinitilogicsolutions/ai-cycle` as **public**, and pushes the initial commit. It refuses to modify a repository that already exists.

## Alternative: create the empty repository in GitHub

Create an empty **public** repository named `ai-cycle` at https://github.com/new. Leave "Initialize with a README" unchecked. After it exists, a connected GitHub session with push rights can upload the contents through GitHub's file/commit tools.

## Before publishing

- Review staged files; public repositories can be cloned immediately.
- Only the CLI's source code, its offline UI, tests, workflow, and documentation belong here. Your application source, PRDs, generated specs, model transcripts, and API keys do not.
- There is no license file. A public GitHub repository is not automatically open-source licensed; choose a license if you want to grant reuse permissions.
- Real Codex/Claude/Spec Kit end-to-end compatibility is not validated yet; local unit tests use fake agents.
