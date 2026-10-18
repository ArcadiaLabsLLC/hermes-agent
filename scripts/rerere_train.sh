#!/usr/bin/env sh
# Teach rerere the conflict resolutions recorded in a branch's merge commits, so
# a later merge that hits the same conflicts replays them (git's contrib
# rerere-train.sh, reduced). Run it in a throwaway worktree: it checks out each
# merge's first parent, re-merges, records the committed result, and aborts the
# re-merge. It never resets: a re-merge that leaves the tree dirty after
# `git merge --abort` stops the run with the worktree as it stands.
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
        # A path the merge's resolution deleted has no blob there: the
        # resolution is the deletion, which rerere does not record.
        for path in $(git diff --name-only --diff-filter=U); do
            if git cat-file -e "$commit:$path" 2>/dev/null; then
                git show "$commit:$path" > "$path"
            else
                rm -f "$path"
            fi
        done
        git rerere >/dev/null
        trained=$((trained + 1))
        echo "learned: $(git log -1 --format='%h %s' "$commit")"
    fi
    git merge --abort >/dev/null 2>&1 || true
    if [ -e "$git_dir/MERGE_HEAD" ] || [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo "rerere_train: the re-merge of $(git rev-parse --short "$commit") left the tree dirty; stopped with the worktree as it stands" >&2
        exit 1
    fi
done
git checkout -q --detach "$start"
echo "rerere_train: $trained merge(s) recorded from $range"
