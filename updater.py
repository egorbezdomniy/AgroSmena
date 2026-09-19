"""Standalone entry point, compiled to updater.exe (onefile, no Qt dependencies)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from updatekit.engine import UpdateTransaction
from updatekit.locking import AppLock


def wait_for_process(pid, timeout=120):
    if not pid:
        return
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # Process already exited.
                return
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError('CRM did not exit; update was not applied')
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(.2)
        raise TimeoutError('CRM did not exit')


def app_command(root):
    return [str(Path(root) / 'AgroSmenaCRM.exe')]


def verify_application(root, data):
    env = os.environ.copy()
    env['AGROSMENA_DATA_ROOT'] = str(data)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    journal = json.loads((Path(data) / 'updates' / 'transaction.json').read_text(encoding='utf-8'))
    env['AGROSMENA_UPDATE_PROBE'] = journal['probe_token']
    log = Path(data) / 'logs' / 'update-startup.log'
    with log.open('ab') as output:
        child = subprocess.Popen(app_command(root) + ['--update-verify'], cwd=root, env=env,
                                 stdout=output, stderr=output)
        try:
            result = child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()  # Never restore SQLite while a migration child is still alive.
            raise RuntimeError('Startup/migration probe timed out')
    if result != 0:
        raise RuntimeError('New CRM failed startup/migration verification; see update-startup.log')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--parent-pid', type=int, default=0)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    root, data = Path(plan['install_root']).resolve(), Path(plan['data_root']).resolve()
    logs = data / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logs / 'updater.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    try:
        wait_for_process(args.parent_pid)
        with AppLock(data):
            transaction = UpdateTransaction(root, data)
            if args.recover:
                if transaction.pending():
                    transaction.rollback()
            else:
                for patch in plan['patches']:
                    path = Path(patch['path']).resolve()
                    if not path.is_relative_to(data / 'updates' / 'downloads'):
                        raise ValueError('Patch outside download cache')
                transaction.apply(plan['patches'], lambda: verify_application(root, data))
        env = os.environ.copy()
        env['AGROSMENA_DATA_ROOT'] = str(data)
        restarted = subprocess.Popen(app_command(root), cwd=root, env=env)
        logging.info('CRM restart requested; pid=%s', restarted.pid)
        return 0
    except Exception:
        logging.exception('Update failed; no unverified CRM will be started')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
