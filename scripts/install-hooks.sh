#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# pre-commit
PRE_COMMIT="$REPO_ROOT/.git/hooks/pre-commit"
cat > "$PRE_COMMIT" << 'HOOK'
#!/usr/bin/env bash
exec "$(git rev-parse --show-toplevel)/scripts/pre-commit/pre-commit.sh"
HOOK
chmod +x "$PRE_COMMIT"
echo "Pre-commit hook installed at $PRE_COMMIT"

# pre-push
PRE_PUSH="$REPO_ROOT/.git/hooks/pre-push"
cat > "$PRE_PUSH" << 'HOOK'
#!/usr/bin/env bash
exec "$(git rev-parse --show-toplevel)/scripts/pre-push/pre-push.sh"
HOOK
chmod +x "$PRE_PUSH"
echo "Pre-push hook installed at $PRE_PUSH"
