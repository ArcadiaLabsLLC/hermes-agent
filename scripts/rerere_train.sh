#!/usr/bin/env sh
# Teach rerere the conflict resolutions recorded in a branch's merge commits, so
# a later merge that hits the same conflicts replays them (git's contrib
# rerere-train.sh, reduced). Run it in a throwaway worktree: it checks out each
# merge's first parent, re-merges, records the committed result, and resets.
#
#   scripts/rerere_train.sh <base>..<branch>
#
# Fork-owned (Harness_Brain/50 — Agent Handoffs/Merging upstream.md, "Daily
# integration branch").
set -eu
range="${1:?usage: scripts/rerere_train.sh <base>..<branch>}"
git config rerere.enabled true
start="$(git rev-parse --verify HEAD)"
git_dir="$(git rev-parse --git-dir)"
trained=0
for commit in $(git rev-list --merges --first-parent --reverse "$range"); do
    parent1="$(git rev-parse "$commit^1")"
    others="$(git rev-parse "$commit^@" | sed 1d)"
    git checkout -q --detach "$parent1"
    # shellcheck disable=SC2086
    git merge --no-ff --no-commit $others >/dev/null 2>&1 || true
    if [ -s "$git_dir/MERGE_RR" ]; then
        # Only the conflicted paths, one blob at a time: a partial clone fetches
        # each lazily, where a whole-tree checkout of the merge does not.
        for path in $(git diff --name-only --diff-filter=U); do
            git show "$commit:$path" > "$path"
        done
        git rerere >/dev/null
        trained=$((trained + 1))
        echo "learned: $(git log -1 --format='%h %s' "$commit")"
    fi
    git merge --abort >/dev/null 2>&1 || git reset -q --hard
done
git checkout -q --detach "$start"
echo "rerere_train: $trained merge(s) recorded from $range"
