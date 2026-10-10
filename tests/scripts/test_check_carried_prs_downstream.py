"""Real git histories exercise carried-hunk drift without touching checkout refs."""
import json
import subprocess

import pytest

from scripts.check_carried_prs import check, ledger_pairs


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          capture_output=True, text=True, encoding='utf-8', timeout=10).stdout.strip()


@pytest.fixture
def history(tmp_path):
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    source = tmp_path / 'code.py'
    source.write_text('def carried():\n    return 1\n\n\ndef independent():\n    return 7\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'base')
    git(tmp_path, 'branch', 'upstream')
    source.write_text(source.read_text().replace('return 1', 'return 2'))
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'PR change')
    git(tmp_path, 'branch', 'pr-head')
    head = git(tmp_path, 'rev-parse', 'HEAD')
    (tmp_path / 'ledger.md').write_text('| `code.py` | PR #12 (open, partial) |\n')
    manifest = {'version': 1, 'prs': {'12': {'head_ref': 'pr-head',
        'reviewed_head': head, 'base_ref': 'upstream',
        'reviewed_base': git(tmp_path, 'rev-parse', 'upstream'),
        'files': {'code.py': {'mode': 'hunks'}}}}}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    return tmp_path, source, manifest


def run(history):
    return check(history[0], 'ledger.md', 'manifest.json')


def save(history):
    (history[0] / 'manifest.json').write_text(json.dumps(history[2]))


def test_carried_hunk_mutation_is_drift(history):
    assert run(history)[0] == 0
    history[1].write_text(history[1].read_text().replace('return 2', 'return 99'))
    code, output = run(history)
    assert code == 1
    assert any(line.startswith('DRIFT PR #12 code.py') for line in output)


def test_fork_additions_outside_carried_hunk_are_not_drift(history):
    with history[1].open('a') as stream:
        stream.write('\n\ndef fork_only():\n    return 10\n')
    assert run(history)[0] == 0


def test_symbol_review_preserves_independent_fork_change(history):
    history[2]['prs']['12']['files']['code.py'] = {'mode': 'symbols', 'symbols': ['carried']}
    save(history)
    history[1].write_text(history[1].read_text().replace('return 7', 'return 19'))
    assert run(history)[0] == 0
    history[1].write_text(history[1].read_text().replace('return 2', 'return 99'))
    assert run(history)[0] == 1


def test_missing_ref_is_error_not_clean(history):
    history[2]['prs']['12']['head_ref'] = 'missing'
    save(history)
    assert run(history)[0] == 2


def test_changed_head_requires_review(history):
    history[1].write_text(history[1].read_text() + '\n# PR review fix\n')
    git(history[0], 'add', 'code.py')
    git(history[0], 'commit', '-m', 'advance PR')
    history[2]['prs']['12']['head_ref'] = 'HEAD'
    save(history)
    code, output = run(history)
    assert code == 2
    assert any('differs from reviewed_head' in line for line in output)


def test_unclassified_ledger_pair_is_error(history):
    with (history[0] / 'ledger.md').open('a') as stream:
        stream.write('| `new.py` | PR #12 (open) |\n')
    assert run(history)[0] == 2


def test_deferred_reference_is_explicit_partial_coverage(history):
    history[2]['prs']['12']['files']['code.py'] = {
        'mode': 'deferred', 'reason': 'widening not adopted'}
    save(history)
    code, output = run(history)
    assert code == 0
    assert any(line.startswith('SKIP ') for line in output)
    assert '0 checked; 1 deferred' in output[-1]
    assert 'partial coverage' in output[-1]


def test_every_open_qualifier_and_symbol_path_is_recognized():
    assert ledger_pairs('| `x.py::f` (also above) | PR #1 (open; partial), PR #2 (open, third-party) |\n'
                        '| `y.py` | PR #3 (closed) |') == {('1', 'x.py'), ('2', 'x.py')}


def test_fork_ref_checks_committed_content_not_dirty_worktree(history):
    history[1].write_text('BROKEN\n')
    assert check(history[0], 'ledger.md', 'manifest.json', 'HEAD')[0] == 0


def test_empty_ledger_is_not_clean(history):
    (history[0] / 'ledger.md').write_text('no matching rows\n')
    with pytest.raises(ValueError, match='refusing empty coverage'):
        run(history)


def fragment_rule(history, **extra):
    history[2]['prs']['12']['files']['code.py'] = {
        'mode': 'lines', 'fragments': ['    return 2'],
        'reason': 'carried return; unrelated fork function retained', **extra}
    save(history)


def test_reviewed_added_fragment_detects_mutation(history):
    fragment_rule(history)
    assert run(history)[0] == 0
    history[1].write_text(history[1].read_text().replace('return 2', 'return 99'))
    assert run(history)[0] == 1


def test_fragment_must_be_current_pr_addition(history):
    fragment_rule(history, fragments=['    return 7'])
    code, output = run(history)
    assert code == 2
    assert any('not in current PR additions' in line for line in output)


def test_reviewed_fragment_relocation_and_fork_changes(history):
    fragment_rule(history, fork_path='relocated.py', fragments=[{
        'text': '    return 2', 'scope_map': {'carried': 'changed_name'}}])
    (history[0] / 'relocated.py').write_text(
        'def changed_name():\n    # fork line\n    return 2\n')
    history[1].unlink()
    code, output = run(history)
    assert code == 0
    assert any('reviewed addition fragments in relocated.py' in line for line in output)
    assert 'partial coverage' in output[-1]


def test_fragment_substring_is_not_sufficient(history):
    fragment_rule(history, fragments=['return 2'])
    assert run(history)[0] == 2


def test_ledger_facade_maps_to_pr_implementation(history):
    fragment_rule(history)
    rule = history[2]['prs']['12']['files'].pop('code.py')
    rule.update(pr_path='code.py', fork_path='code.py')
    history[2]['prs']['12']['files']['facade.py'] = rule
    (history[0] / 'ledger.md').write_text('| `facade.py` | PR #12 (open) |\n')
    save(history)
    assert run(history)[0] == 0
    history[1].write_text(history[1].read_text().replace('return 2', 'return 99'))
    assert run(history)[0] == 1


def test_missing_expected_fork_file_is_drift(history):
    fragment_rule(history, fork_path='missing.py')
    assert run(history)[0] == 1
    assert check(history[0], 'ledger.md', 'manifest.json', 'HEAD')[0] == 1


def test_reviewed_identifier_mapping_detects_mutated_carry(history):
    fragment_rule(history, fragments=[{'text': '    return 2',
                                      'fork_path': 'adapted.py', 'scope_map': {'carried': 'moved'}}])
    (history[0] / 'adapted.py').write_text('def moved():\n    return 2\n')
    assert run(history)[0] == 0
    (history[0] / 'adapted.py').write_text('def moved():\n    return 9\n')
    assert run(history)[0] == 1


def test_identifier_replacement_is_validated_against_pr_before_mapping(history):
    # PR adds a call; fork extracts/renames its helper without changing the call contract.
    history[1].write_text('def carried():\n    return original_helper()\n')
    git(history[0], 'add', 'code.py')
    git(history[0], 'commit', '-m', 'PR helper call')
    history[2]['prs']['12']['head_ref'] = 'HEAD'
    history[2]['prs']['12']['reviewed_head'] = git(history[0], 'rev-parse', 'HEAD')
    fragment_rule(history, fragments=[{'text': '    return original_helper()',
                                      'replacements': {'original_helper': 'fork_helper'}}])
    history[1].write_text('def carried():\n    return fork_helper()\n')
    assert run(history)[0] == 0
    history[1].write_text('def carried():\n    return other_helper()\n')
    assert run(history)[0] == 1


@pytest.mark.parametrize("field", ["default", "forwarding", "doctor"])
def test_production_duplicate_mutation_is_drift(history, field):
    """Use the real carried production source and manifest, without remote refs."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    path = "tests/hermes_cli/test_doctor.py" if field == "doctor" else "agent/conversation_loop.py"
    number = "125260" if field == "doctor" else "124210"
    production = root / path
    source = production.read_text(encoding="utf-8")
    rules = json.loads((root / "tests/fixtures/carried_prs.json").read_text(encoding="utf-8"))
    rule = rules["prs"][number]["files"][path]
    # An isolated empty base makes every real production fragment a PR addition.
    history[1].write_text("")
    git(history[0], "add", "code.py")
    git(history[0], "commit", "-m", "empty production baseline")
    git(history[0], "branch", "production-base")
    history[1].write_text(source, encoding="utf-8")
    git(history[0], "add", "code.py")
    git(history[0], "commit", "-m", "real production carried surface")
    entry = history[2]["prs"]["12"]
    entry.update(head_ref="HEAD", reviewed_head=git(history[0], "rev-parse", "HEAD"),
                 base_ref="production-base", reviewed_base=git(history[0], "rev-parse", "production-base"))
    entry["files"]["code.py"] = rule
    save(history)
    assert run(history)[0] == 0
    text = ("reuse_current_user_message: bool = False" if field == "default"
            else "reuse_current_user_message=reuse_current_user_message")
    replacement = ("reuse_current_user_message: bool = True" if field == "default"
                   else "reuse_current_user_message=False")
    if field == "doctor":
        text = 'monkeypatch.setenv("HERMES_HOME", str(hermes_home))'
        replacement = 'monkeypatch.setenv("WRONG_HOME", str(hermes_home))'
    assert source.count(text) >= 2
    history[1].write_text(source.replace(text, replacement, 1), encoding="utf-8")
    assert run(history)[0] == 1


def test_duplicate_occurrences_in_one_symbol_require_exact_count(history):
    source = 'def carried():\n    value = 2\n    value = 2\n    return value\n'
    history[1].write_text(source)
    git(history[0], 'add', 'code.py')
    git(history[0], 'commit', '-m', 'duplicate carried assignments')
    entry = history[2]['prs']['12']
    entry.update(head_ref='HEAD', reviewed_head=git(history[0], 'rev-parse', 'HEAD'))
    fragment_rule(history, fragments=['    value = 2'])
    assert run(history)[0] == 0
    history[1].write_text(source.replace('value = 2', 'value = 9', 1))
    assert run(history)[0] == 1


def test_fork_only_duplicate_cannot_mask_changed_carried_symbol(history):
    fragment_rule(history)
    source = history[1].read_text() + '\n\ndef fork_only():\n    return 2\n'
    history[1].write_text(source)
    assert run(history)[0] == 0
    history[1].write_text(source.replace('return 2', 'return 99', 1))
    assert run(history)[0] == 1


def test_unrelated_insertions_inside_carried_symbol_are_allowed(history):
    fragment_rule(history)
    history[1].write_text(history[1].read_text().replace('    return 2',
        '    # independently ledgered fork addition\n    fork_value = 99\n    return 2'))
    assert run(history)[0] == 0


def test_moving_fragment_to_wrong_symbol_is_drift(history):
    fragment_rule(history)
    history[1].write_text('def wrong_symbol():\n    return 2\n')
    assert run(history)[0] == 1


def test_advanced_base_requires_review_even_with_unchanged_head(history):
    # Simulate upstream absorbing this PR while the reviewed PR head stays put.
    history[2]['prs']['12']['base_ref'] = 'pr-head'
    save(history)
    code, output = run(history)
    assert code == 2
    assert any('differs from reviewed_base' in line for line in output)


def test_manifest_pair_removed_from_ledger_is_error(history):
    history[2]['prs']['12']['files']['stale.py'] = {
        'mode': 'deferred', 'reason': 'formerly recorded reference'}
    save(history)
    code, output = run(history)
    assert code == 2
    assert any('manifest pair absent' in line for line in output)


def test_invalid_fork_ref_cannot_hide_behind_deferred_coverage(history):
    history[2]['prs']['12']['files']['code.py'] = {
        'mode': 'deferred', 'reason': 'not adopted'}
    save(history)
    assert check(history[0], 'ledger.md', 'manifest.json', 'does-not-exist')[0] == 2


def test_missing_reviewed_base_is_error(history):
    del history[2]['prs']['12']['reviewed_base']
    save(history)
    assert run(history)[0] == 2
