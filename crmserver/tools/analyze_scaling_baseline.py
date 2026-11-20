"""Read experiment artifacts only; never imports Django or opens a database."""
import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from scaling_baseline import summarize, write_json


def analyze(root):
    root = root.resolve()
    events = defaultdict(list)
    for path in sorted(root.glob('events-*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            events[event['request_id']].append(event)
    samples = [json.loads(line) for line in (root / 'samples.jsonl').read_text(encoding='utf-8').splitlines()]
    for row in samples:
        for event in events[row['request_id']]:
            if event['event'] == 'baseline_transport':
                row['wsgi_response_ready_ms'] = event['wsgi_response_ready_ms']
            elif event['event'] == 'http_request':
                row['server_finished_utc'] = event['timestamp']
    results = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    environment = json.loads((root / 'environment.json').read_text(encoding='utf-8'))
    project = Path(__file__).resolve().parents[1]
    unchanged = all(hashlib.sha256((project / name).read_bytes()).hexdigest() == value
                    for name, value in environment['source_sha256'].items())
    missing = [row['request_id'] for row in samples if row['mode'] == 'sql' and row['status'] == 200
               and ('sql_count' not in row or 'server_ms' not in row)]
    observations_path = root / 'db-observations.jsonl'
    observations = [json.loads(line) for line in observations_path.read_text(encoding='utf-8').splitlines()] if observations_path.exists() else []
    for event in observations:
        event['_epoch'] = datetime.fromisoformat(event['timestamp']).timestamp()
    for group in results['results']:
        if group['category'] != 'concurrency':
            continue
        rows = [row for row in samples if all(row[key] == group[key] for key in
                ('category', 'scenario', 'organization', 'parallel', 'mode', 'block'))]
        ends = [datetime.fromisoformat(row['server_finished_utc']).timestamp() for row in rows if 'server_finished_utc' in row]
        starts = [datetime.fromisoformat(row['server_finished_utc']).timestamp() - row['server_ms'] / 1000
                  for row in rows if 'server_finished_utc' in row]
        selected = [event for event in observations if starts and min(starts) <= event['_epoch'] <= max(ends)]
        group['db_wait_observation_n'] = len(selected)
        group['db_waiters_max'] = max((event['lock_waiters'] for event in selected), default=None)
        group['db_wait_observations_positive'] = sum(event['lock_waiters'] > 0 for event in selected)
    buckets = defaultdict(list)
    for row in samples:
        if row['category'] == 'overhead':
            buckets[(row['scenario'], row['mode'])].append(row)
    overhead = []
    for (scenario, mode), rows in buckets.items():
        summary = summarize(rows)
        wsgi = sorted(row['wsgi_response_ready_ms'] for row in rows)
        summary['wsgi_response_ready_ms'] = {'median': statistics.median(wsgi), 'n': len(wsgi),
                                           'min': min(wsgi), 'max': max(wsgi)}
        groups = [group for group in results['results'] if group['category'] == 'overhead'
                  and group['scenario'] == scenario and group['mode'] == mode]
        summary['server_cpu_mean_ms_per_request'] = sum(group.get('server_cpu_seconds', 0) for group in groups) * 1000 / len(rows)
        summary['rss_after_max_mib'] = max(group['resources_after'].get('rss_bytes', 0) for group in groups) / 1048576
        blocks = {block: statistics.median(row['client_ms'] for row in rows if row['block'] == block)
                  for block in {row['block'] for row in rows}}
        overhead.append({'scenario': scenario, 'mode': mode, 'block_client_medians': blocks, **summary})
    mixed = []
    subsets = defaultdict(list)
    for row in samples:
        if row['scenario'] == 'crm_during_sync':
            subsets[(row['parallel'], row.get('route', 'unknown'))].append(row)
    for (parallel, route), rows in subsets.items():
        mixed.append({'parallel': parallel, 'route': route, **summarize(rows)})
    profiles = []
    index_path = root / 'profile-index.jsonl'
    for line in index_path.read_text(encoding='utf-8').splitlines() if index_path.exists() else []:
        index = json.loads(line)
        path = root / 'profiles' / (index['request_id'] + '.json')
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        profiles.append({**index, 'groups': data.get('groups', []), 'plans': data.get('plans', [])})
    return {'environment': environment, 'raw': results, 'overhead': overhead, 'mixed': mixed,
            'profiles': profiles, 'samples': samples, 'source_unchanged': unchanged,
            'missing_sql_correlations': missing,
            'total_samples': len(samples), 'total_errors': sum(row['status'] != 200 for row in samples)}


def short(value, digits=1):
    return f'{value:.{digits}f}' if value is not None else '—'


def med(row, key):
    return row.get(key, {}).get('median')


def pair(row, key):
    return short(med(row, key)) + ' / ' + short(row.get(key, {}).get('p95'))


def tables(data):
    lines = []
    results = data['raw']['results']
    for org in ('small', 'medium', 'large'):
        lines += [f'### {org}', '',
                  '| Сценарий | n / ошибки | HTTP med / p95, мс | app med / p95, мс | SQL count / SQL ms (med) | Ответ, KiB | CPU mean ms/req | RSS после, MiB |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- |']
        for row in results:
            if row['category'] == 'sequential' and row['organization'] == org:
                lines.append(f"| {row['scenario']} | {row['n']} / {row['errors']} | {pair(row, 'client_ms')} | "
                    f"{pair(row, 'server_ms')} | {short(med(row, 'sql_count'),0)} / {short(med(row, 'sql_duration_ms'))} | "
                    f"{short(med(row, 'response_bytes') / 1024) if med(row, 'response_bytes') is not None else '—'} | "
                    f"{short(row.get('server_cpu_seconds',0)*1000/row['n'])} | "
                    f"{short(row['resources_after'].get('rss_bytes',0)/1048576)} |")
        lines += ['']
    lines += ['### Фазы sync: медианы в мс', '',
              '| Набор / сценарий | n / ошибки | validation | acquire (включая SQL) | observed hold | apply | prepare | service |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in results:
        if row['category'] == 'sequential' and row['scenario'].startswith('sync'):
            lines.append(f"| {row['organization']} / {row['scenario']} | {row['n']} / {row['errors']} | " +
                ' | '.join(short(med(row, field)) for field in (
                    'input_validation_ms', 'organization_lock_acquire_ms', 'organization_lock_observed_hold_ms',
                    'apply_ms', 'response_prepare_ms', 'exchange_service_ms')) + ' |')
    lines += ['', '### Конкуренция', '',
              '| Набор / сценарий | Клиенты | n / ошибки | HTTP med / p95, мс | app med / p95, мс | executor queue med / max, мс | acquire med / max, мс | DB waiters max | Время серии, с |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in results:
        if row['category'] == 'concurrency':
            client_text = 'см. маршруты ниже' if row['scenario'] == 'crm_during_sync' else pair(row, 'client_ms')
            server_text = 'см. маршруты ниже' if row['scenario'] == 'crm_during_sync' else pair(row, 'server_ms')
            lines.append(f"| {row['organization']} / {row['scenario']} | {row['parallel']} | {row['n']} / {row['errors']} | "
                f"{client_text} | {server_text} | {short(med(row,'executor_queue_ms'))} / "
                f"{short(row.get('executor_queue_ms',{}).get('max'))} | {short(med(row,'organization_lock_acquire_ms'))} / "
                f"{short(row.get('organization_lock_acquire_ms',{}).get('max'))} | {group_waiters(row)} | {row['wall_seconds']:.1f} |")
    lines += ['', 'Смешанная серия отдельно по маршрутам (не смешивать их latency):', '',
              '| Клиенты | Маршрут | n / ошибки | HTTP med / p95, мс | app med, мс |',
              '| --- | --- | --- | --- | --- |']
    for row in data['mixed']:
        lines.append(f"| {row['parallel']} | {row['route']} | {row['n']} / {row['errors']} | {pair(row,'client_ms')} | {short(med(row,'server_ms'))} |")
    lines += ['', '### Диагностика: три блока, объединённые 60 наблюдений на режим/операцию', '',
              '| Операция | Режим | n / ошибки | HTTP med / p95, мс | WSGI ready med, мс | SQL n / ms (med) | CPU mean ms/req | RSS после max, MiB | Медианы блоков HTTP, мс |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in sorted(data['overhead'], key=lambda value: (value['scenario'], value['mode'])):
        lines.append(f"| {row['scenario']} | {row['mode']} | {row['n']} / {row['errors']} | {pair(row,'client_ms')} | "
            f"{short(med(row,'wsgi_response_ready_ms'))} | {short(med(row,'sql_count'),0)} / {short(med(row,'sql_duration_ms'))} | "
            f"{short(row['server_cpu_mean_ms_per_request'])} | {short(row['rss_after_max_mib'])} | " +
            ', '.join(short(value) for key,value in sorted(row['block_client_medians'].items())) + ' |')
    return '\n'.join(lines) + '\n'


def group_waiters(row):
    return str(row['db_waiters_max']) if row.get('db_waiters_max') is not None else '—'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    data = analyze(args.root)
    write_json(args.root / 'analysis.json', {key: value for key,value in data.items() if key != 'samples'})
    (args.root / 'result-tables.md').write_text(tables(data), encoding='utf-8')
    print(json.dumps({key: data[key] for key in ('total_samples', 'total_errors', 'source_unchanged', 'missing_sql_correlations')}))


if __name__ == '__main__':
    main()
