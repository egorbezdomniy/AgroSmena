"""Offline summaries; never connects to a DB or rewrites the original reports."""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from scaling_baseline import summarize, write_json


def read_run(root, paired=False):
    result = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    groups = result['results']
    rows = [json.loads(line) for line in (root / 'samples.jsonl').read_text(encoding='utf-8').splitlines()]
    excluded = []
    if paired:
        present = defaultdict(set)
        for group in groups:
            present[group['block'], group['organization']].add(group['category'])
        complete = {key for key, variants in present.items() if len(variants) == 2}
        # Older harness versions discarded client warmup results. A server-side
        # failure/over-limit warmup is not a comparable successful process history.
        counts = {org['label']: org['admin_snapshot_records'] for org in
                  json.loads((root / 'dataset.json').read_text(encoding='utf-8'))['organizations']}
        measured_ids = {row['request_id'] for row in rows}
        for path in root.glob('events-*.jsonl'):
            events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            ids = {event.get('request_id') for event in events}
            related = [row for row in rows if row['request_id'] in ids]
            for event in events:
                if (event.get('event') != 'sync_exchange' or event['request_id'] in measured_ids
                        or event['status_code'] == 200 and event['duration_ms'] < 45000):
                    continue
                for row in related:
                    key = row['block'], row['organization']
                    if key in complete and event.get('incoming_records') == counts[row['organization']]:
                        complete.remove(key)
                        excluded.append({'block': key[0], 'organization': key[1],
                            'reason': 'Unmeasured server warmup failed or reached the 45s HTTP limit; client result unavailable',
                            'request_id': event['request_id'], 'server_status': event['status_code'],
                            'server_ms': event['duration_ms']})
        groups = [g for g in groups if (g['block'], g['organization']) in complete]
        rows = [r for r in rows if (r['block'], r['organization']) in complete]
    return groups, rows, excluded


def aggregate(groups, rows):
    buckets = defaultdict(list)
    for row in rows:
        key = (row['category'], row['organization'], row['scenario'], row['parallel'])
        buckets[key].append(row)
    output = []
    for key, values in buckets.items():
        related = [g for g in groups if (g['category'], g['organization'], g['scenario'], g['parallel']) == key]
        attempts = sum(g['n'] for g in related)
        peaks = [g['resources_after']['process_lifetime_peak_rss_bytes'] / 2**20 for g in related
                 if g['resources_after'].get('available')]
        rss = [g['resources_after']['rss_bytes'] / 2**20 for g in related if g['resources_after'].get('available')]
        output.append(dict(zip(('category', 'organization', 'scenario', 'parallel'), key),
            **summarize(values), cpu_ms_per_attempt=sum(g.get('server_cpu_seconds', 0) for g in related) * 1000 / attempts,
            peak_working_set_mib=max(peaks) if peaks else None,
            median_working_set_mib=statistics.median(rss) if rss else None))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ab', nargs='*', type=Path, default=[])
    parser.add_argument('--run', nargs='*', type=Path, default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'ab_paired_only': [], 'runs': {}}
    for root in args.ab:
        groups, rows, excluded = read_run(root, paired=True)
        result['ab_paired_only'].append({'root': str(root), 'groups': groups,
                                        'excluded_pairs': excluded, 'summary': aggregate(groups, rows)})
    for root in args.run:
        groups, rows, _ = read_run(root)
        result['runs'][str(root)] = {'summary': aggregate(groups, rows), 'groups': groups}
    write_json(args.output, result)
    for experiment in [*result['ab_paired_only'], *result['runs'].values()]:
        for row in experiment['summary']:
            print(row['category'], row['organization'], row['scenario'], row['n'], row['errors'],
                  'HTTP', round(row.get('client_ms', {}).get('median', 0), 1),
                  'SQL', row.get('sql_count', {}).get('median'),
                  'CPU', round(row['cpu_ms_per_attempt'], 1), 'peakMiB', round(row['peak_working_set_mib'], 1))


if __name__ == '__main__':
    main()
