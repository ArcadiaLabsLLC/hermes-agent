"""scripts/build/node-deps.mjs: the reuse receipt and the npm ci retries.

A fake npm CLI (reached through ``npm_execpath``) records each ``npm ci`` and can
fail the way npm does on Windows when a loaded native binding is held open:
exit 1 with ``EPERM … unlink '<path>'`` in the run's debug log.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
HELD = "C:\\src\\node_modules\\lightningcss-win32-x64-msvc\\lightningcss.win32-x64-msvc.node"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required")

FAKE_NPM = r"""
const { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } = require('node:fs')
const { join } = require('node:path')
const args = process.argv.slice(2)
if (args[0] !== 'ci') process.exit(0)
const state = process.env.FAKE_NPM_STATE
appendFileSync(join(state, 'calls'), 'ci\n')
const failures = existsSync(join(state, 'eperm')) ? Number(readFileSync(join(state, 'eperm'), 'utf8')) : 0
if (failures > 0) {
  writeFileSync(join(state, 'eperm'), String(failures - 1))
  const logs = args.find(arg => arg.startsWith('--logs-dir=')).slice('--logs-dir='.length)
  writeFileSync(join(logs, 'debug-0.log'),
    `0 verbose stack Error: EPERM: operation not permitted, unlink '${process.env.FAKE_NPM_HELD}'\n`
    + `1 error code EPERM\n2 error path ${process.env.FAKE_NPM_HELD}\n`)
  process.exit(1)
}
mkdirSync('node_modules', { recursive: true })
writeFileSync(join('node_modules', '.package-lock.json'), JSON.stringify({ packages: {} }))
"""

DRIVER = r"""
import { prepareNodeDependencies } from %s
const env = JSON.parse(process.argv[2])
try {
  prepareNodeDependencies({ source: process.argv[3], workspaces: ['ws'], env, reuse: true })
} catch (error) {
  console.log('THROWN ' + error.message)
  process.exit(3)
}
"""


@pytest.fixture
def checkout(tmp_path):
    source = tmp_path / "source"
    (source / "ws").mkdir(parents=True)
    (source / "package.json").write_text(json.dumps({"name": "root", "workspaces": ["ws"]}))
    (source / "ws" / "package.json").write_text(json.dumps({"name": "ws", "version": "1.0.0"}))
    (source / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"name": "root"}, "node_modules/ws": {"resolved": "ws", "link": True}, "ws": {"name": "ws"}}}))
    npm = tmp_path / "npm"
    (npm / "bin").mkdir(parents=True)
    (npm / "bin" / "npm-cli.js").write_text(FAKE_NPM)
    (npm / "package.json").write_text(json.dumps({"version": "10.0.0"}))
    (npm / "node_modules" / "semver").mkdir(parents=True)
    (npm / "node_modules" / "semver" / "index.js").write_text("exports.satisfies = () => true\n")
    state = tmp_path / "state"
    state.mkdir()
    driver = tmp_path / "driver.mjs"
    module = (REPO / "scripts" / "build" / "node-deps.mjs").as_uri()
    driver.write_text(DRIVER % json.dumps(module))
    base = {"PATH": os.environ.get("PATH", ""), "npm_execpath": str(npm / "bin" / "npm-cli.js"),
            "FAKE_NPM_STATE": str(state), "FAKE_NPM_HELD": HELD}
    for key in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
        if key in os.environ:
            base[key] = os.environ[key]

    def prepare(extra=None):
        env = {**base, **(extra or {})}
        return subprocess.run([NODE, str(driver), json.dumps(env), str(source)],
                              capture_output=True, text=True, timeout=120, check=False)

    def calls():
        path = state / "calls"
        return len(path.read_text().splitlines()) if path.exists() else 0

    return prepare, calls, state


def test_npm_injected_lifecycle_keys_do_not_rekey_the_receipt(checkout):
    prepare, calls, _ = checkout
    assert prepare().returncode == 0
    assert calls() == 1
    injected = {
        "npm_config_user_agent": "npm/12.0.2 node/v26.7.0 win32 x64 workspaces/false",
        "NPM_CONFIG_USERCONFIG": "C:\\home\\npmrc",
        "npm_config_global_prefix": "C:\\node", "npm_config_local_prefix": "C:\\src",
        "npm_config_node_gyp": "C:\\node\\node-gyp.js", "npm_config_npm_version": "12.0.2",
    }
    result = prepare(injected)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reusing completed install" in result.stdout
    assert calls() == 1


def test_a_real_npm_config_still_rekeys_the_receipt(checkout):
    prepare, calls, _ = checkout
    assert prepare().returncode == 0
    assert prepare({"npm_config_omit": "optional"}).returncode == 0
    assert calls() == 2


def test_eperm_on_a_held_binding_retries_once_and_names_the_path(checkout):
    prepare, calls, state = checkout
    (state / "eperm").write_text("1")
    result = prepare()
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls() == 2
    assert f"EPERM on {HELD}" in result.stdout


def test_a_second_eperm_raises_naming_the_held_path(checkout):
    prepare, calls, state = checkout
    (state / "eperm").write_text("2")
    result = prepare()
    assert result.returncode == 3
    assert calls() == 2
    assert f"THROWN npm ci failed twice with EPERM: {HELD} is held open" in result.stdout
