"""The read-only probe honors the harness's shared presentation contract."""
import json
from types import SimpleNamespace

from agent_runtime.execution_identity import execution_identity
from hermes_cli.harness_parts.parser.execution_identity import print_execution_identity


def test_execution_identity_projection_and_quiet_output(capsys):
    identity = execution_identity()["execution_id"]
    args = SimpleNamespace(json=False, output="json", fields="execution_id", quiet=False)
    assert print_execution_identity(args) == 0
    assert json.loads(capsys.readouterr().out) == {"execution_id": identity}
    args.fields = None
    args.quiet = True
    assert print_execution_identity(args) == 0
    assert capsys.readouterr().out.strip() == identity
