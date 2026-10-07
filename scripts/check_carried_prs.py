#!/usr/bin/env python3
"""Compare reviewed carried PR hunks, never whole upstream files.

Fetch the manifest's refs before running; this command is read-only and offline.
Every open-PR ledger file must be classified. Deferred references are printed, not
counted as checked. A changed fetched head requires a fresh applicability review.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

LEDGER = 'docs/agent-runtime-harness/planned/upstream-footprint-ledger.md'
MANIFEST = 'tests/fixtures/carried_prs.json'


def git(repo, *args, env=None, input=None):
    result = subprocess.run(['git', '-C', str(repo), *args], input=input,
                            capture_output=True, text=True, env=env, timeout=30)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'git command failed')
    return result.stdout


def ledger_pairs(text):
    pairs = set()
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        first = line.split('|')[1]
        path_match = re.search(r'`([^`]+)`', first)
        if not path_match:
            continue
        path = path_match[1].split('::', 1)[0]
        for number in re.findall(r'PR #(\d+) \(open\b', line):
            pairs.add((number, path))
    return pairs


def symbol_source(text, name):
    nodes = ast.parse(text).body
    node = None
    for part in name.split('.'):
        node = next((item for item in nodes if isinstance(item, (ast.FunctionDef,
                    ast.AsyncFunctionDef, ast.ClassDef)) and item.name == part), None)
        if node is None:
            raise ValueError(f'missing symbol {name}')
        nodes = node.body
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return '\n'.join(text.splitlines()[start - 1:node.end_lineno])


def added_blocks(patch):
    """Return contiguous added-line blocks, excluding patch headers."""
    blocks, current = [], []
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith('@@ '):
            in_hunk = True
        if in_hunk and line.startswith('+'):
            current.append(line[1:])
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def contains_lines(lines, fragment):
    wanted = fragment.splitlines()
    return bool(wanted) and any(lines[index:index + len(wanted)] == wanted
                                for index in range(len(lines) - len(wanted) + 1))


def fork_source(repo, path, ref):
    if ref:
        # Validate the tree separately so a missing file is drift, not a bad-ref error.
        git(repo, 'rev-parse', '--verify', ref + '^{tree}')
        present = git(repo, 'ls-tree', '--name-only', ref, '--', path).strip()
        return git(repo, 'show', f'{ref}:{path}') if present else ''
    file = repo / path
    return file.read_text() if file.exists() else ''


def check(repo, ledger=LEDGER, manifest=MANIFEST, fork_ref=None):
    repo = Path(repo)
    pairs = ledger_pairs((repo / ledger).read_text())
    if not pairs:
        raise ValueError('ledger contains no open-PR file rows; refusing empty coverage')
    data = json.loads((repo / manifest).read_text())
    if data.get('version') != 1:
        raise ValueError('unsupported manifest version')
    checked = deferred = drift = errors = partial = 0
    output = []
    pins = {}
    for number, path in sorted(pairs, key=lambda pair: (int(pair[0]), pair[1])):
        label = f'PR #{number} {path}'
        try:
            entry = data['prs'][number]
            if number not in pins:
                head = git(repo, 'rev-parse', '--verify', entry['head_ref'] + '^{commit}').strip()
                if head != entry['reviewed_head']:
                    raise ValueError(f'fetched head {head} differs from reviewed_head; review manifest')
                base = git(repo, 'merge-base', entry['base_ref'], head).strip()
                pins[number] = head, base
            head, base = pins[number]
            rule = entry['files'][path]
            mode = rule['mode']
            if mode == 'deferred':
                reason = rule['reason'].strip()
                if not reason:
                    raise ValueError('deferred row needs a reason')
                output.append(f'SKIP {label}: {reason}')
                deferred += 1
                continue
            pr_path = rule.get('pr_path', path)
            changed = git(repo, 'diff', '--name-only', base, head, '--', pr_path).strip()
            if not changed:
                raise ValueError('path has no PR delta; classify reference or review moved file')
            coverage = ''
            if mode == 'lines':
                fragments = rule['fragments']
                reason = rule['reason'].strip()
                if not reason or not fragments:
                    raise ValueError('lines mode needs nonempty fragments and review reason')
                patch = git(repo, 'diff', '--no-renames', '--unified=0', base, head, '--', pr_path)
                additions = added_blocks(patch)
                matches = True
                fork_path = rule.get('fork_path', path)
                for item in fragments:
                    spec = {'text': item} if isinstance(item, str) else item
                    fragment = spec['text']
                    if not fragment.strip() or not any(contains_lines(block, fragment) for block in additions):
                        raise ValueError('reviewed fragment is not in current PR additions')
                    for old, new in spec.get('replacements', {}).items():
                        if not old.isidentifier() or not new.isidentifier():
                            raise ValueError('fragment replacements must be identifiers')
                        fragment, count = re.subn(r'\b' + re.escape(old) + r'\b', new, fragment)
                        if not count:
                            raise ValueError('replacement identifier missing from PR fragment')
                    ours = fork_source(repo, spec.get('fork_path', fork_path), fork_ref)
                    matches = contains_lines(ours.splitlines(), fragment) and matches
                partial += 1
                coverage = (f' [reviewed addition fragments in {fork_path}; '
                            f'deletions/unselected changes not checked: {reason}]')
            elif mode == 'symbols':
                symbols = rule['symbols']
                if not symbols:
                    raise ValueError('empty symbol selection')
                theirs = git(repo, 'show', f'{head}:{pr_path}')
                ours = (git(repo, 'show', f'{fork_ref}:{path}') if fork_ref
                        else (repo / path).read_text())
                matches = all(symbol_source(theirs, name) == symbol_source(ours, name)
                              for name in symbols)
            elif mode == 'hunks':
                patch = git(repo, 'diff', '--binary', '--no-renames', base, head, '--', path)
                with tempfile.TemporaryDirectory(prefix='carried-pr-index-') as directory:
                    env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / 'index'))
                    git(repo, 'read-tree', fork_ref or 'HEAD', env=env)
                    if not fork_ref:
                        git(repo, 'add', '-A', '--', path, env=env)
                    result = subprocess.run(['git', '-C', str(repo), 'apply', '--cached',
                                             '--reverse', '--check', '-'], input=patch,
                                            capture_output=True, text=True, env=env, timeout=30)
                    matches = result.returncode == 0
            else:
                raise ValueError(f'unknown mode {mode!r}')
            checked += 1
            if matches:
                output.append(f'OK {label}{coverage}')
            else:
                drift += 1
                output.append(f'DRIFT {label}: carried {mode} differ from {head}{coverage}')
        except (KeyError, ValueError, OSError, subprocess.TimeoutExpired, SyntaxError) as exc:
            errors += 1
            output.append(f'ERROR {label}: {exc}')
    output.append(f'Summary: {len(pairs)} ledger pairs; {checked} checked; {deferred} deferred; '
                  f'{drift} drift; {errors} errors' + (f' (partial coverage: {partial} fragment selections)' if deferred or partial else ''))
    return (2 if errors else 1 if drift else 0), output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ledger', default=LEDGER)
    parser.add_argument('--manifest', default=MANIFEST)
    parser.add_argument('--fork-ref', help='compare a committed fork ref instead of working files')
    args = parser.parse_args(argv)
    try:
        code, output = check(args.repo, args.ledger, args.manifest, args.fork_ref)
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}')
        return 2
    print('\n'.join(output))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
