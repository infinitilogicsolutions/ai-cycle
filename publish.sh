#!/usr/bin/env bash
# Publishes the AI Cycle source to a new public GitHub repository.
# Requires an authenticated GitHub CLI: gh auth login
set -euo pipefail

cd "$(dirname "$0")"
OWNER="${GITHUB_OWNER:-infinitilogicsolutions}"
NAME="${GITHUB_REPO:-ai-cycle}"
FULL="$OWNER/$NAME"

for cmd in gh git python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing '$cmd'. Install it before publishing." >&2
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

LOGIN="$(gh api user --jq .login)"
if [ "$LOGIN" != "$OWNER" ]; then
  echo "Authenticated GitHub account is '$LOGIN', not '$OWNER'." >&2
  echo "Switch accounts or explicitly set GITHUB_OWNER if publishing to an account/org you control." >&2
  exit 1
fi

if gh repo view "$FULL" >/dev/null 2>&1; then
  echo "Repository https://github.com/$FULL already exists; refusing to overwrite it." >&2
  exit 1
fi

echo "Running the included test suite..."
python3 -m unittest discover -s tests -q

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  TOP="$(git rev-parse --show-toplevel)"
  if [ "$TOP" != "$PWD" ]; then
    echo "Run from a standalone extracted directory, not a subfolder of another Git repo." >&2
    exit 1
  fi
else
  git init -b main
fi

# Publish only a known allowlist, not 'git add --all' from an unknown folder.
git add .gitignore .github/workflows/tests.yml README.md MODEL_SELECTION.md \
  START-HERE.html PUBLISHING.md pyproject.toml ai_cycle tests examples publish.sh

if git diff --cached --quiet && ! git rev-parse HEAD >/dev/null 2>&1; then
  echo "No source files were staged." >&2
  exit 1
fi

echo
echo "The following files will be PUBLIC at https://github.com/$FULL:"
git ls-files | sed 's/^/  /'
echo
echo "Private PRD/spec artifacts and credentials are NOT included by default."
read -r -p 'Type PUBLISH to create the public repository: ' ANSWER
if [ "$ANSWER" != "PUBLISH" ]; then
  echo "Cancelled. Nothing published."
  exit 0
fi

if ! git rev-parse HEAD >/dev/null 2>&1; then
  git commit -m 'Initial public release of AI Cycle CLI and guided wizard'
else
  if ! git diff --cached --quiet; then
    git commit -m 'Publish AI Cycle CLI and guided wizard'
  fi
fi

gh repo create "$FULL" --public --source=. --remote=origin --push
echo "Published: https://github.com/$FULL"
