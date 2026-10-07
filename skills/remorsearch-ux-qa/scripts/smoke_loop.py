#!/usr/bin/env python3
"""Offline acceptance smoke for the loop. It needs only the skill folder (an installed copy or a
repository checkout): the fixtures come from examples/ and uxloop/demo_factory.py, and everything it
writes goes to a disposable folder (.ux-loop/ in a repository checkout, else the system temp folder)."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # skill folder: scripts, uxloop, examples
sys.path.insert(0, str(ROOT))

from uxloop.demo_factory import BASE_BUNDLE, make_packet  # Authored fixtures, never live provider output.
from uxloop.io import load_json


def runtime_root() -> Path:
    """Where disposable output goes: .ux-loop/ (git-ignored) in a repository checkout, else the system
    temp folder. Resolved, because the loop refuses output paths that pass through a symlink."""
    checkout = ROOT.parents[1]
    if (checkout / 'tests' / '_paths.py').is_file():
        runtime = checkout / '.ux-loop'
        runtime.mkdir(exist_ok=True)
        return runtime.resolve()
    return Path(tempfile.gettempdir()).resolve()


def invalid_bundles(folder: Path) -> list:
    """Broken copies of the example bundle, one for each validator rule the smoke check exercises."""
    base = json.loads(BASE_BUNDLE.read_text(encoding='utf-8'))
    edits = {
        'broken-ref': lambda records: records['evidence'][0].update(source_id='source-missing'),
        'missing-id': lambda records: records['claims'][0].pop('id'),
        'synthetic-claim': lambda records: records['claims'][0].update(claim_kind='user_preference',
                                                                       persona_ids=['persona-1']),
        'verified-no-observation': lambda records: records['findings'][0].update(observation_ids=['observation-missing']),
    }
    paths = []
    for name, edit in edits.items():
        bundle = copy.deepcopy(base)
        edit(bundle['records'])
        path = folder / f'invalid-{name}.json'
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        paths.append(path)
    return paths


def main() -> int:
    argparse.ArgumentParser(
        description='Run offline loop acceptance checks using authored fixtures only; '
                    'no live integrations or browser are executed. Temporary outputs '
                    'are removed after the run (.ux-loop/ in a checkout, otherwise '
                    'the system temporary folder).'
    ).parse_args()
    outcomes = []
    runtime = runtime_root()

    def command(arguments: list[str], expected: int) -> dict:
        result = subprocess.run([sys.executable, *arguments], cwd=ROOT, capture_output=True,
                                text=True, timeout=30)
        if result.returncode != expected:
            raise AssertionError(f'{arguments}: wanted {expected}, got {result.returncode}\n{result.stdout}\n{result.stderr}')
        outcomes.append({'command': 'python3 ' + ' '.join(arguments), 'exit': result.returncode, 'expected_exit': expected})
        return json.loads(result.stdout) if result.stdout.lstrip().startswith('{') else {}

    try:
        command(['scripts/validate_bundle.py', 'examples/bundle/minimal.json'], 0)
        value = command(['scripts/ux_loop.py', 'validate', 'examples/loop/packet.json', '--evidence-root', 'examples/loop'], 0)
        assert value['valid'] and value['completion_assessed'] is False
        with tempfile.TemporaryDirectory(dir=runtime, prefix='smoke-') as temporary:
            root = Path(temporary)
            for path in invalid_bundles(root):
                command(['scripts/validate_bundle.py', str(path)], 1)
            denied = command(['scripts/ux_loop.py', 'demo', '--output', str(root / 'denied')], 3)
            assert denied['status'] == 'blocked' and denied['accepted_fix_ids'] == []
            site = root / 'resumable'
            interrupted = command(['scripts/ux_loop.py', 'demo', '--output', str(site), '--grant', 'code_write',
                '--actor', 'smoke-supervisor', '--reason', 'Approve only the isolated fixture patch', '--pause-after', 'browser'], 6)
            checkpoint = site / 'checkpoint.json'
            before = load_json(checkpoint)
            assert interrupted['status'] == 'interrupted' and interrupted['accepted_fix_ids'] == []
            completed = command(['scripts/ux_loop.py', 'resume', '--checkpoint', str(checkpoint)], 0)
            after = load_json(checkpoint)
            assert before['run_id'] == after['run_id'] and before['permissions'] == after['permissions']
            assert before['packet']['bundle']['records']['evidence'] == after['packet']['bundle']['records']['evidence']
            assert completed['accepted_fix_ids'] == ['fix-1'] and completed['product_complete'] is False
            assert '상품 상세 보기' in (site / 'site/index.html').read_text(encoding='utf-8')
            command(['scripts/ux_loop.py', 'resume', '--checkpoint', str(checkpoint)], 0)
            for case, code, status in [('failed_visual', 5, 'failed'), ('unknown_evidence', 4, 'unknown'),
                                       ('regression_failure', 5, 'failed'), ('missing_browser', 3, 'blocked')]:
                directory = root / case
                make_packet(directory, case)
                workspace = directory / 'site'
                workspace.mkdir()
                (workspace / 'index.html').write_bytes((ROOT / 'examples/loop/site/index.html').read_bytes())
                result = command(['scripts/ux_loop.py', 'run', str(directory / 'packet.json'), '--workspace', str(workspace),
                    '--evidence-root', str(directory), '--checkpoint', str(directory / 'checkpoint.json'),
                    '--grant', 'code_write', '--actor', 'smoke-supervisor', '--reason', 'Approve isolated fixture code'], code)
                assert result['status'] == status and not result['product_complete'] and result['accepted_fix_ids'] == []
            malformed = root / 'malformed.json'
            malformed.write_text('{"schema_version":"ux-loop.v1","schema_version":"unsafe"}', encoding='utf-8')
            command(['scripts/ux_loop.py', 'validate', str(malformed)], 2)
        print(json.dumps({'passed': True, 'command_count': len(outcomes), 'checks': outcomes,
                          'live_integrations_executed': False}, indent=2))
        return 0
    except (AssertionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'passed': False, 'reason': str(exc), 'completed_checks': outcomes}, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
