#!/usr/bin/env bash
set -euo pipefail

# secret-scan.sh
# Scans staged files for obvious secrets using regexes. Exits non-zero if any match
# Whitelist rules: .env.example, *.md files (allow pattern definitions), files containing FAKE_KEY_

GIT_STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)
if [ -z "$GIT_STAGED_FILES" ]; then
  exit 0
fi

declare -a REGEXES=(
  'sk-[A-Za-z0-9]{20,}'
  'ntn_[A-Za-z0-9]{20,}'
  'ghp_[A-Za-z0-9]{36,}'
  'sbp_[A-Za-z0-9]{20,}'
  'eyJ[A-Za-z0-9-_]{30,}'
  '[0-9]{8,10}:[A-Za-z0-9_-]{35}'
)

FAIL=0

for file in $GIT_STAGED_FILES; do
  # Skip deleted files
  if [ ! -e "$file" ]; then
    continue
  fi

  # Whitelist: .env.example
  if [[ "$file" == ".env.example" ]]; then
    continue
  fi

  # Read file content from index (staged content)
  CONTENT=$(git show :"$file" 2>/dev/null || true)
  if [ -z "$CONTENT" ]; then
    continue
  fi

  # Skip markdown files where pattern definitions might appear
  if [[ "$file" == *.md ]]; then
    # But still allow FAKE_KEY_ to pass: if a markdown contains a real-looking key but labelled FAKE_KEY_, ignore
    echo "Skipping markdown file: $file"
    continue
  fi

  # Skip files that include FAKE_KEY_ (test fixtures)
  if echo "$CONTENT" | grep -q 'FAKE_KEY_' ; then
    continue
  fi

  for rx in "${REGEXES[@]}"; do
    # Use grep -E for portability (macOS/BSD grep doesn't support -P by default)
    if printf "%s" "$CONTENT" | grep -En -m 1 "$rx" >/dev/null 2>&1; then
      echo "[secret-scan] SECRET PATTERN MATCH in $file -> $rx"
      printf "%s" "$CONTENT" | grep -En "$rx" | sed -n '1,5p'
      FAIL=1
    fi
  done
done

if [ "$FAIL" -ne 0 ]; then
  echo "\nCommit blocked by secret-scan hook. Remove secrets or add to whitelist if intentional." >&2
  exit 1
fi

exit 0
