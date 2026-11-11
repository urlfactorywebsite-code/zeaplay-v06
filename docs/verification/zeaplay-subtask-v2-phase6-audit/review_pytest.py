"""Disposable Phase 0 runner; never use from an installed application folder."""
import inspect
import os
from pathlib import Path
import socket
import sys

os.chdir(Path(__file__).parent)
os.environ.update(VEE_DATABASE_URL='sqlite:///:memory:', VEE_ENVIRONMENT='test',
                  VEE_JWT_SECRET_KEY='phase0-fixture-signing-key',
                  VEE_JWT_REFRESH_SECRET_KEY='phase0-fixture-refresh-key',
                  VEE_REDIS_URL='', VEE_CACHE_REDIS_URL='',
                  VEE_ENABLE_N8N_FORWARDING='false', PYTHONDONTWRITEBYTECODE='1')
for key in ('ZEA_BACKUP_TEST_URL', 'ZEA_REVIEW_POSTGRES_URL'):
    os.environ.pop(key, None)
sys.dont_write_bytecode = True
original_connect = socket.socket.connect

def guarded_connect(self, address):
    caller = inspect.currentframe().f_back
    if (address == ('127.0.0.1', 15467)):
        return original_connect(self, address)
    if (caller.f_code.co_filename == socket.__file__
            and caller.f_code.co_name == '_fallback_socketpair'):
        return original_connect(self, address)
    raise RuntimeError('Phase 0: outbound sockets blocked')

socket.socket.connect = guarded_connect
import faulthandler
faulthandler.dump_traceback_later(45, repeat=True)
import pytest

result = pytest.main(sys.argv[1:] + ['-q', '--tb=short', '-p', 'no:cacheprovider'])
faulthandler.cancel_dump_traceback_later()
raise SystemExit(result)
