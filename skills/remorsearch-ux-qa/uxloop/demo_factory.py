"""Authored, explicitly synthetic loop packets for the demo, the smoke check and the tests.

Nothing here runs a browser, reads a live page or calls a provider. make_packet writes a fresh
packet and its receipt files under a directory, starting from the example evidence bundle that
ships with the skill (examples/bundle/minimal.json), so scripts/smoke_loop.py runs from an
installed copy of the skill folder alone. The same builder gives the negative cases the tests use,
without pretending that fixtures are live screenshots, real Figma reads or real-user research.
"""
from __future__ import annotations

import copy
import difflib
import json
from pathlib import Path

from .io import digest, sha

SKILL = Path(__file__).resolve().parents[1]
BASE_BUNDLE = SKILL / 'examples' / 'bundle' / 'minimal.json'

START = '2026-09-14T00:00:00+00:00'
CAPTURE = '2026-09-14T00:01:00+00:00'
END = '2026-09-14T00:02:00+00:00'
REPLAY_START = '2026-09-14T00:03:00+00:00'
REPLAY_CAPTURE = '2026-09-14T00:04:00+00:00'
REPLAY_END = '2026-09-14T00:05:00+00:00'
REGRESSION_AT = '2026-09-14T00:06:00+00:00'


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def make_packet(root: Path, case: str = 'happy') -> dict:
    """Write a fresh synthetic packet and supporting test fixtures under root."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'artifacts').mkdir(exist_ok=True)
    original = (SKILL / 'examples/loop/site/index.html').read_text(encoding='utf-8')
    fixed = original.replace('>다음</a>', '>상품 상세 보기</a>')
    before, after = digest({'index.html': original}), digest({'index.html': fixed})
    bundle = json.loads(BASE_BUNDLE.read_text(encoding='utf-8'))
    bundle['bundle_id'] = 'bundle-loop-fixture-1'
    records = bundle['records']
    records['sources'][0].update({'channel': 'fixture', 'source_ref': 'fixture://not-real-user-research',
                                  'access_method': 'authored-test-fixture', 'public_scope': 'synthetic-fixture'})
    records['evidence'][0].pop('excerpt', None)
    records['evidence'][0]['summary'] = 'Synthetic test input for the contract, not a real community observation.'
    records['claims'][0].update({'epistemic_status': 'inferred', 'verification_status': 'unverified',
                                'statement': 'Hypothesis: a specific action label may clarify the next step.'})
    records['figma'][0].update({'read_at': START, 'readback_artifact_ref': 'artifact-figma'})
    records['runs'][0]['id'] = 'baseline-1'
    records['runs'][0]['surface_ref'] = 'https://example.test/product'
    records['runs'].append({'id': 'replay-1', 'scenario_id': 'scenario-1', 'status': 'completed',
                            'surface_ref': 'https://example.test/product'})
    records['observations'][0]['run_id'] = 'baseline-1'
    records['observations'][0]['result'] = 'Fixture scenario: the next action label is ambiguous.'
    scenario = {'id': 'scenario-1', 'version': '1', 'origin': 'https://example.test', 'route': '/product',
                'viewport': {'width': 390, 'height': 844, 'device_scale_factor': 1}, 'device': 'mobile-390',
                'input_method': 'keyboard',
                'fixture': {'id': 'fixture-1', 'revision': 'seed-1', 'account_ref': 'anonymous-isolated', 'isolated': True},
                'steps': [{'id': 'step-open', 'action': 'Open /product in a fresh isolated browser context',
                           'expected': 'Search results and the next action are visible', 'requires': 'read_only'},
                          {'id': 'step-keyboard', 'action': 'Tab to the action and activate with Enter',
                           'expected': 'Focus is visible and the product detail opens', 'requires': 'read_only'}],
                'a11y_checks': ['keyboard', 'focus', 'semantics', 'contrast']}
    packet = {'schema_version': 'ux-loop.v1', 'mode': 'fixture',
              'goal': {'id': 'goal-action-label', 'objective': 'Make the next action explicit within the declared sample scenario',
                       'scenario_ids': ['scenario-1'], 'evidence_ids': ['evidence-1'], 'max_iterations': 2,
                       'code_paths': ['index.html'], 'stop_conditions': {x: True for x in [
                           'all_scenarios_pass', 'all_findings_replayed', 'visual_pass', 'accessibility_pass', 'regression_pass', 'no_unknowns']}},
              'policy': {'figma_first': True, 'allow_side_accents': False, 'raw_community_storage': False, 'retention_days': 7},
              'bundle': bundle, 'scenarios': [scenario], 'artifacts': [], 'browser_runs': [], 'visual_checks': [],
              'fixes': [], 'rounds': [], 'replays': []}

    def add(artifact_id: str, kind: str, content: str | dict, at: str, extension: str = 'json') -> str:
        path = 'artifacts/' + artifact_id + '.' + extension
        raw = ((json.dumps(content, ensure_ascii=False, indent=2) + '\n') if isinstance(content, dict) else content).encode()
        (root / path).write_bytes(raw)
        packet['artifacts'].append({'id': artifact_id, 'path': path, 'sha256': sha(raw), 'kind': kind,
                                    'provenance': 'fixture', 'created_at': at})
        return artifact_id

    figma = records['figma'][0]
    add('artifact-figma', 'figma_readback', {**{k: figma[k] for k in (
        'file_key', 'branch_key', 'baseline_version', 'readback_version', 'node_ids', 'read_at')}, 'editable': True,
        'fixture_notice': 'Authored contract fixture, not an actual Figma file/readback.'}, START)
    reference_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="390" height="844" data-ux-fixture="true"><title>Not a live screenshot</title><text x="20" y="40">Fixture: explicit action label</text></svg>\n'
    add('artifact-reference', 'screenshot', reference_svg, START, 'svg')
    for phase, run_id, rev, start, capture, end in [
        ('baseline', 'baseline-1', before, START, CAPTURE, END),
        ('replay', 'replay-1', after, REPLAY_START, REPLAY_CAPTURE, REPLAY_END),
    ]:
        step_art = 'artifact-' + phase + '-steps'
        a11y_art = 'artifact-' + phase + '-a11y'
        steps = [{'step_id': x['id'], 'outcome': 'passed', 'actual': 'Authored fixture outcome; not a browser execution.',
                  'artifact_ids': [step_art]} for x in scenario['steps']]
        accessibility = [{'name': name, 'status': 'passed', 'detail': 'Synthetic fixture coverage only.', 'artifact_id': a11y_art}
                         for name in scenario['a11y_checks']]
        run = {'id': run_id, 'scenario_id': scenario['id'], 'scenario_digest': digest(scenario), 'phase': phase,
               'outcome': 'passed' if phase == 'replay' else 'failed', 'epistemic_status': 'observed', 'execution': 'fixture',
               'operator': 'fixture-author-not-a-real-tester',
               'tool': {'name': 'authored-fixture', 'version': '1', 'browser': 'not-executed', 'browser_version': 'not-executed'},
               'code_revision': rev, 'started_at': start, 'ended_at': end,
               'environment': {**{k: scenario[k] for k in ('origin', 'route', 'viewport', 'device')},
                               'fixture_id': 'fixture-1', 'fixture_revision': 'seed-1', 'account_ref': 'anonymous-isolated',
                               'session_id': 'isolated-' + phase},
               'steps': steps, 'accessibility': accessibility, 'evidence': {},
               'reason': '' if phase == 'replay' else 'Fixture finding: action label does not specify its destination.'}
        identity = {'run_id': run_id, 'scenario_digest': digest(scenario), 'code_revision': rev}
        for kind in ('console', 'network', 'runtime'):
            run['evidence'][kind] = add('artifact-' + phase + '-' + kind, kind,
                                       {**identity, 'kind': kind, 'unexpected_errors': [], 'fixture_notice': 'No live telemetry collected.'}, capture)
        add(step_art, 'steps', {**identity, 'kind': 'steps', 'results': steps}, capture)
        add(a11y_art, 'accessibility', {**identity, 'kind': 'accessibility', 'results': accessibility}, capture)
        actual_art = add('artifact-' + phase + '-capture', 'screenshot', reference_svg.replace('explicit action label', phase + ' fixture'), capture, 'svg')
        visual = {'id': 'visual-' + phase, 'run_id': run_id, 'figma_id': 'figma-1',
                  **{k: figma[k] for k in ('node_ids', 'file_key', 'branch_key', 'baseline_version', 'readback_version')},
                  'route': scenario['route'], 'viewport': copy.deepcopy(scenario['viewport']),
                  'actual_artifact_id': actual_art, 'reference_artifact_id': 'artifact-reference',
                  'comparison_artifact_id': 'artifact-' + phase + '-visual', 'status': 'passed',
                  'method': 'review', 'reviewer': 'fixture-author',
                  'checks': {name: 'passed' for name in ('layout', 'interaction_states', 'typography', 'side_accents')}, 'reason': ''}
        if phase == 'baseline' or (phase == 'replay' and case == 'failed_visual'):
            visual.update({'status': 'failed', 'reason': 'Synthetic comparison: ambiguous action label.'})
            visual['checks']['interaction_states'] = 'failed'
        add(visual['comparison_artifact_id'], 'visual_report', {**identity, 'kind': 'visual_report', 'comparison': visual}, capture)
        packet['browser_runs'].append(run)
        packet['visual_checks'].append(visual)
    patch = ''.join(difflib.unified_diff(original.splitlines(True), fixed.splitlines(True), fromfile='a/index.html', tofile='b/index.html'))
    patch_id = add('artifact-patch', 'code_patch', patch, START, 'patch')
    packet['fixes'] = [{'id': 'fix-1', 'proposal_id': 'proposal-1', 'finding_ids': ['finding-1'], 'kind': 'code_write',
                        'changed_paths': ['index.html'], 'patch_artifact_id': patch_id, 'before_revision': before,
                        'after_revision': after, 'figma_id': 'figma-1', 'rationale': 'Clarify the destination of the next action.',
                        'expected_effect': 'The fixture label names the product-detail action; real-user benefit remains unmeasured.'}]
    packet['rounds'] = [{'id': 'round-1', 'number': 1, 'baseline_run_ids': ['baseline-1'], 'fix_ids': ['fix-1']}]
    regression_status = 'failed' if case == 'regression_failure' else 'passed'
    regression_id = add('artifact-regression', 'regression', {'kind': 'regression', 'replay_id': 'replay-set-1',
        'code_revision': after, 'run_ids': ['replay-1'], 'scenario_ids': ['scenario-1'], 'status': regression_status,
        'failed_checks': ['fixture-adjacent-state'] if regression_status == 'failed' else []}, REGRESSION_AT)
    packet['replays'] = [{'id': 'replay-set-1', 'round_id': 'round-1', 'run_ids': ['replay-1'],
                         'regression': {'status': regression_status, 'artifact_id': regression_id,
                                        'scenario_ids': ['scenario-1'], 'code_revision': after, 'detail': 'Synthetic regression fixture only.'}}]
    if case == 'unknown_evidence':
        records['evidence'][0]['epistemic_status'] = 'unknown'
    elif case == 'missing_browser':
        packet['rounds'] = []
        packet['replays'] = []
    elif case == 'blocked_permission':
        # Deliberately claims historical code permission: never an operational grant.
        bundle['permissions']['requested'].append('code_write')
        bundle['permissions']['granted'].append('code_write')
    elif case not in {'happy', 'failed_visual', 'regression_failure', 'interrupted'}:
        raise ValueError('Unknown fixture case: ' + case)
    write_json(root / 'packet.json', packet)
    return packet


def replace_artifact(packet: dict, root: Path, artifact_id: str, edit) -> None:
    item = next(x for x in packet['artifacts'] if x['id'] == artifact_id)
    path = root / item['path']
    value = json.loads(path.read_text(encoding='utf-8'))
    edit(value)
    write_json(path, value)
    item['sha256'] = sha(path.read_bytes())


def append_recovery_round(packet: dict, root: Path) -> dict:
    """Append passing, newly identified receipts; preserve every failed old receipt."""
    newer = copy.deepcopy(packet)
    template = copy.deepcopy(packet['browser_runs'][1])
    template_visual = copy.deepcopy(packet['visual_checks'][1])
    artifacts = {x['id']: x for x in packet['artifacts']}
    for phase, minute in [('baseline', 10), ('replay', 13)]:
        run_id = phase + '-2'
        capture = f'2026-09-14T00:{minute + 1:02d}:00+00:00'
        selected = {template['evidence'][k] for k in ('console', 'network', 'runtime')}
        selected.update(x for step in template['steps'] for x in step['artifact_ids'])
        selected.update(x['artifact_id'] for x in template['accessibility'])
        selected.update([template_visual['actual_artifact_id'], template_visual['comparison_artifact_id']])
        replacements = {x: x + '-' + phase + '-2' for x in selected}
        replacements.update({template['id']: run_id, template['environment']['session_id']: 'isolated-' + run_id,
                             template_visual['id']: 'visual-' + run_id})

        def rewrite(value):
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [rewrite(x) for x in value]
            if isinstance(value, dict):
                return {k: rewrite(v) for k, v in value.items()}
            return value

        browser = rewrite(template)
        browser.update({'phase': phase, 'outcome': 'passed', 'reason': '',
                        'started_at': f'2026-09-14T00:{minute:02d}:00+00:00',
                        'ended_at': f'2026-09-14T00:{minute + 2:02d}:00+00:00'})
        visual = rewrite(template_visual)
        visual.update({'status': 'passed', 'reason': '', 'checks': {k: 'passed' for k in visual['checks']}})
        for artifact_id in sorted(selected):
            item = copy.deepcopy(artifacts[artifact_id])
            oldpath = root / item['path']
            item.update({'id': replacements[artifact_id], 'created_at': capture,
                         'path': 'artifacts/' + replacements[artifact_id] + oldpath.suffix})
            if oldpath.suffix == '.json':
                content = rewrite(json.loads(oldpath.read_text(encoding='utf-8')))
                if item['kind'] == 'visual_report':
                    content['comparison'] = visual
                write_json(root / item['path'], content)
            else:
                (root / item['path']).write_bytes(oldpath.read_bytes())
            item['sha256'] = sha((root / item['path']).read_bytes())
            newer['artifacts'].append(item)
        newer['browser_runs'].append(browser)
        newer['visual_checks'].append(visual)
        newer['bundle']['records']['runs'].append({'id': run_id, 'scenario_id': browser['scenario_id'],
                                                   'status': 'completed', 'surface_ref': browser['environment']['origin'] + browser['environment']['route']})
    newer['rounds'].append({'id': 'round-2', 'number': 2, 'baseline_run_ids': ['baseline-2'], 'fix_ids': []})
    regression = copy.deepcopy(packet['replays'][0])
    regression.update({'id': 'replay-set-2', 'round_id': 'round-2', 'run_ids': ['replay-2']})
    regression['regression'].update({'artifact_id': 'artifact-regression-2', 'status': 'passed'})
    payload = {'kind': 'regression', 'replay_id': 'replay-set-2', 'code_revision': template['code_revision'],
               'run_ids': ['replay-2'], 'scenario_ids': ['scenario-1'], 'status': 'passed', 'failed_checks': []}
    path = 'artifacts/artifact-regression-2.json'
    write_json(root / path, payload)
    newer['artifacts'].append({'id': 'artifact-regression-2', 'path': path, 'sha256': sha((root / path).read_bytes()),
                               'kind': 'regression', 'provenance': 'fixture', 'created_at': '2026-09-14T00:16:00+00:00'})
    newer['replays'].append(regression)
    return newer
