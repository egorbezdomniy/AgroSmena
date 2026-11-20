"""Synthetic-only phase CPU/GC probes, installed only in owned diagnostic copies."""
import ctypes
import gc
import json
import threading
import time
from contextlib import contextmanager


def install(root):
    from baseline_data import assert_disposable
    from synchronization import services
    if assert_disposable() != root:
        raise RuntimeError('CPU probes require the owned synthetic cluster')
    local = threading.local()
    lock = threading.Lock()
    target = root / 'phase-cpu.jsonl'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.QueryThreadCycleTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)]

    def cycles():
        value = ctypes.c_ulonglong()
        if not kernel.QueryThreadCycleTime(kernel.GetCurrentThread(), ctypes.byref(value)):
            return None
        return value.value

    def reference():
        start, cpu, clock = time.perf_counter(), time.thread_time(), cycles()
        value = 0
        for i in range(100000):
            value = (value * 33 + i) % 1000003
        end_clock = cycles()
        return {'wall_ms': (time.perf_counter() - start) * 1000,
                'cpu_ms': (time.thread_time() - cpu) * 1000,
                'cycles': end_clock - clock if clock is not None and end_clock is not None else None,
                'checksum': value, 'iterations': 100000}

    def gc_event(event, info):
        state = getattr(local, 'state', None)
        if state is None:
            return
        if event == 'start':
            state['gc_start'] = time.perf_counter()
        else:
            state['gc_ms'] += (time.perf_counter() - state['gc_start']) * 1000
            state['gc_collections'][info['generation']] += 1

    gc.callbacks.append(gc_event)
    original = services.sync_phase

    @contextmanager
    def phase(request, name):
        if name not in ('apply_ms', 'response_prepare_ms'):
            with original(request, name):
                yield
            return
        probe = reference()  # Before native phase timing; diagnostic requests only.
        state = {'gc_ms': 0, 'gc_collections': [0, 0, 0]}
        local.state = state
        start, cpu, clock = time.perf_counter(), time.thread_time(), cycles()
        success = False
        try:
            with original(request, name):
                yield
            success = True
        finally:
            local.state = None
            end_clock = cycles()
            event = {'phase': name, 'request_id': getattr(request, 'request_id', ''),
                     'success': success, 'wall_ms': (time.perf_counter() - start) * 1000,
                     'cpu_ms': (time.thread_time() - cpu) * 1000,
                     'cycles': end_clock - clock if clock is not None and end_clock is not None else None,
                     'gc_ms': state['gc_ms'], 'gc_collections': state['gc_collections'], 'reference': probe}
            with lock, target.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event) + '\n')

    services.sync_phase = phase
