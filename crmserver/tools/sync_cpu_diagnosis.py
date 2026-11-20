"""Four fresh processes ABBA; same no-op large packets, CPU/GC probes outside app code."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import scaling_baseline as baseline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--before-source', type=Path, required=True)
    parser.add_argument('--current-source', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=900, choices=range(120, 1201))
    parser.add_argument('--anchor-date', default='2026-10-16')
    args = parser.parse_args()
    current = baseline.PROJECT
    experiment = baseline.Experiment(args)
    variants = {}
    try:
        manifest = {}
        for name, source in [('A', args.before_source), ('B', args.current_source)]:
            source = source.resolve(strict=True)
            if any(p.is_symlink() or p.name.startswith('.env') for p in source.rglob('*')):
                raise RuntimeError('Frozen source unexpectedly contains environment files or links')
            destination = experiment.root / f'source-{name}'
            shutil.copytree(source, destination)
            server = destination / 'tools/baseline_server.py'
            text = server.read_text(encoding='utf-8')
            needle = '    app = get_wsgi_application()\n'
            if text.count(needle) != 1:
                raise RuntimeError('Unexpected diagnostic server source')
            server.write_text(text.replace(needle, needle +
                '    from sync_cpu_probe import install\n    install(root)\n'), encoding='utf-8')
            shutil.copyfile(Path(__file__).with_name('sync_cpu_probe.py'), destination / 'tools/sync_cpu_probe.py')
            variants[name] = destination
            manifest[name] = {'frozen_source': str(source), 'sha256': {
                rel: hashlib.sha256((destination / rel).read_bytes()).hexdigest() for rel in (
                    'synchronization/services.py', 'tasks/serializers.py', 'tools/baseline_server.py', 'tools/sync_cpu_probe.py')}}
        baseline.write_json(experiment.root / 'diagnostic-sources.json', manifest)
        experiment.setup()
        experiment.start_server('sql')
        org = next(org for org in experiment.data['organizations'] if org['label'] == 'large')
        response = experiment.http(org, '/api/sync/exchange/', {'organization': org['uuid'], 'changes': []}, retain=True)
        if response['status'] != 200:
            raise RuntimeError('Cannot prepare synthetic packet')
        packet = {'organization': org['uuid'], 'changes': response['body']['changes']}
        experiment.stop_server()
        for block, variant in enumerate('ABBA'):
            baseline.PROJECT = variants[variant]
            experiment.env['PYTHONPATH'] = os.pathsep.join((str(baseline.PROJECT), str(baseline.PROJECT / 'tools')))
            experiment.start_server('sql')
            def operation(i):
                row = experiment.http(org, '/api/sync/exchange/', packet)
                if i < 0:
                    with (experiment.root / 'warmup-samples.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps({'block': block, 'category': variant, 'index': i, **row}) + '\n')
                    if row['status'] != 200:
                        raise RuntimeError('Diagnostic warmup failed; process history is not comparable')
                return row
            experiment.group(org, 'sync_unchanged_cpu_probe',
                operation,
                repeats=1, warmup=2, category=variant, block=block)
            experiment.stop_server()
    except BaseException as exc:
        experiment.unfinished.append({'error_type': type(exc).__name__, 'reason': str(exc)})
        raise
    finally:
        baseline.PROJECT = current
        experiment.finish()


if __name__ == '__main__':
    main()
