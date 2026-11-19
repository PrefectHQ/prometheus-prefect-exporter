#!/usr/bin/env bash
# A re-run of a stale Release must not publish or tag a version or commit at or behind the latest release.
set -eu

exit_code=0
remote_tags=$(git ls-remote --tags "https://github.com/$GITHUB_REPOSITORY" 'refs/tags/*') || exit_code=$?
if [ "$exit_code" -ne 0 ]; then
  echo "::error::Could not list the remote tags (git ls-remote exit $exit_code)"
  exit 1
fi
highest=$(printf '%s\n' "$remote_tags" | sed -e 's|^.*refs/tags/||' -e '/\^{}$/d' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)
if [ -z "$highest" ]; then
  echo "::error::No version tags found on the remote"
  exit 1
fi
above=$(printf '%s\n%s\n' "$highest" "$VERSION" | sort -V | tail -n 1)
if [ "$highest" = "$VERSION" ] || [ "$above" != "$VERSION" ]; then
  echo "::error::$VERSION is not above the latest release $highest; dispatch a new Release instead of re-running this one"
  exit 1
fi
exit_code=0
comparison=$(gh api "repos/$GITHUB_REPOSITORY/compare/$highest...$GITHUB_SHA" --jq .status) || exit_code=$?
if [ "$exit_code" -ne 0 ]; then
  echo "::error::Could not compare $GITHUB_SHA with $highest (gh api exit $exit_code)"
  exit 1
fi
if [ "$comparison" != "ahead" ]; then
  echo "::error::$GITHUB_SHA is not ahead of the latest release $highest (compare status: $comparison); dispatch a new Release instead of re-running this one"
  exit 1
fi
