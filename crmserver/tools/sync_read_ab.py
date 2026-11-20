"""Alternating read-optimization A/B; fresh HTTP processes, one owned synthetic DB.

Uses the unchanged baseline request, diagnostics, resource sampler and limits.
The frozen source is read only. No working-tree reset and no deployed settings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import scaling_baseline as baseline


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(body):
    content = {key: body[key] for key in ('changes', 'members')}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--before-source', type=Path, required=True)
    parser.add_argument('--blocks', type=int, default=4, choices=(2, 4))
    parser.add_argument('--repeats', type=int, default=2, choices=(1, 2))
    parser.add_argument('--max-seconds', type=int, default=1800, choices=range(120, 1801))
    parser.add_argument('--anchor-date', default='2026-10-16')
    args = parser.parse_args()
    current = baseline.PROJECT
    before = args.before_source.resolve(strict=True)
    if before == current or not (before / 'tools/baseline_server.py').is_file():
        parser.error('A separate frozen server source directory is required')
    variants = {'A_before_read': before, 'B_current_read': current}
    hashes = {name: {file: digest(root / file) for file in (
        'synchronization/services.py', 'tasks/serializers.py', 'tools/baseline_server.py',
        'tools/baseline_data.py', 'crmserver/baseline_settings.py', 'crmserver/verification_settings.py',
    )} for name, root in variants.items()}
    for file in ('tools/baseline_server.py', 'tools/baseline_data.py',
                 'crmserver/baseline_settings.py', 'crmserver/verification_settings.py'):
        if hashes['A_before_read'][file] != hashes['B_current_read'][file]:
            parser.error(f'Experiment source differs: {file}')
    experiment = baseline.Experiment(args)
    baseline.write_json(experiment.root / 'variants.json', {
        'sources': {key: str(value) for key, value in variants.items()}, 'sha256': hashes,
        'orders': ['AB' if block % 2 == 0 else 'BA' for block in range(args.blocks)],
        'warmup_per_org': 2, 'repeats_per_org': args.repeats,
        'fresh_http_process_per_variant_per_block': True,
    })
    try:
        experiment.setup()
        organizations = [org for org in experiment.data['organizations'] if org['label'] in ('medium', 'large')]
        experiment.start_server('sql')
        packets, expected = {}, {}
        for org in organizations:
            result = experiment.http(org, '/api/sync/exchange/', {'organization': org['uuid'], 'changes': []}, retain=True)
            if result['status'] != 200 or len(result['body']['changes']) != org['admin_snapshot_records']:
                raise RuntimeError('Cannot prepare complete synthetic packet')
            packets[org['label']] = {'organization': org['uuid'], 'changes': result['body']['changes']}
            expected[org['label']] = fingerprint(result['body'])
        experiment.stop_server()
        baseline.write_json(experiment.root / 'packet-fingerprints.json', expected)
        for block in range(args.blocks):
            order = list(variants) if block % 2 == 0 else list(reversed(variants))
            for variant in order:
                baseline.PROJECT = variants[variant]
                experiment.env['PYTHONPATH'] = os.pathsep.join((str(baseline.PROJECT), str(baseline.PROJECT / 'tools')))
                experiment.start_server('sql')
                pid = experiment.server.pid
                for org in organizations:
                    packet = packets[org['label']]
                    def operation(i, org=org, packet=packet):
                        row = experiment.http(org, '/api/sync/exchange/', packet)
                        if i < 0:
                            with (experiment.root / 'warmup-samples.jsonl').open('a', encoding='utf-8') as stream:
                                stream.write(json.dumps({'block': block, 'category': variant,
                                    'organization': org['label'], 'index': i, **row}) + '\n')
                            if row['status'] != 200:
                                raise RuntimeError('A/B warmup failed; process history is not comparable')
                        return row
                    # Same complete unchanged packet and process history on both sides.
                    result = experiment.group(org, 'sync_unchanged',
                        operation,
                        repeats=args.repeats, warmup=2, category=variant, block=block)
                    result.update(server_pid=pid, source=str(baseline.PROJECT))
                    experiment.save()
                experiment.stop_server()
        # Unmeasured final content checks, separated from all measured blocks.
        checks = {}
        for variant, source in variants.items():
            baseline.PROJECT = source
            experiment.env['PYTHONPATH'] = os.pathsep.join((str(source), str(source / 'tools')))
            experiment.start_server('sql')
            checks[variant] = {}
            for org in organizations:
                result = experiment.http(org, '/api/sync/exchange/', packets[org['label']], retain=True)
                actual = fingerprint(result['body']) if result['status'] == 200 else None
                checks[variant][org['label']] = {'status': result['status'], 'sha256': actual,
                                                'matches': actual == expected[org['label']]}
            experiment.stop_server()
        baseline.write_json(experiment.root / 'content-checks.json', checks)
        if not all(row['matches'] for variant in checks.values() for row in variant.values()):
            raise RuntimeError('Snapshot content mismatch')
    except BaseException as exc:
        experiment.unfinished.append({'error_type': type(exc).__name__, 'reason': str(exc)})
        raise
    finally:
        baseline.PROJECT = current
        experiment.finish()


if __name__ == '__main__':
    main()
