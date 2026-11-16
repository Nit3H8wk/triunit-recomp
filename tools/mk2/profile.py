"""Prepare isolated MK2 CMOS storage; no native launch or guest state conversion.

Payloads are exactly 16384 opaque bytes, preserving both bytes of all 8192
CMOS words. The authenticated factory seed is the existing MAME-product seed,
not native cold DEFAULT_ALL_0. Native valid-CMOS reset branches remain unqualified.
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality

from tools.setup import mk2 as _setup_mk2
FACTORY_SEED=_setup_mk2.seed_path()   # written by the local setup (tools/setup/mk2.py, factory_seed()); not versioned
FACTORY_SHA256='f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f'
SIZE=16384


def _unlinked(path):
    path=Path(path).absolute()
    for item in (path,*path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError('Linked CMOS profile path: '+str(item))
    return path


def _read(path,*,factory=False):
    path=_unlinked(path)
    with path.open('rb') as stream:data=stream.read(SIZE+1)
    if len(data)!=SIZE:raise ValueError('CMOS image must contain exactly 16384 bytes')
    if factory and hashlib.sha256(data).hexdigest()!=FACTORY_SHA256:
        raise ValueError('Factory CMOS seed SHA-256 differs')
    return data


@contextmanager
def _writer(directory):
    lock=_unlinked(directory/'.cmos.lock')
    # A stale/crashed lock fails closed; another session's lock is never removed.
    stream=lock.open('xb')
    try:yield
    finally:
        stream.close()
        _unlinked(lock).unlink()


def _atomic(path,data):
    path=_unlinked(path)
    pending=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.cmos-pending-',dir=path.parent,delete=False) as stream:
            pending=Path(stream.name)
            if stream.write(data)!=len(data):raise OSError('Incomplete CMOS write')
            stream.flush();os.fsync(stream.fileno())
        _unlinked(path);_unlinked(pending)
        os.replace(pending,path)
    finally:
        if pending is not None and pending.exists():_unlinked(pending).unlink()


def load(directory):
    """Read exact persisted bytes; corrupt/missing files are never repaired."""
    directory=_unlinked(directory)
    _read(directory/'factory-seed.bin',factory=True)
    return _read(directory/'cmos.bin')


def prepare(directory,*,seed=FACTORY_SEED):
    """Initialize only an empty explicit profile, keeping its seed immutable."""
    data=_read(seed,factory=True)
    directory=_unlinked(directory)
    directory.mkdir(parents=True,exist_ok=True)
    with _writer(directory):
        seed_path=directory/'factory-seed.bin'
        current=directory/'cmos.bin'
        if seed_path.exists():
            return load(directory)
        else:
            if any(item.name!='.cmos.lock' for item in directory.iterdir()):
                raise ValueError('CMOS profile directory is not empty or owned')
            _atomic(seed_path,data)
        created=seed_path.stat()
        try:_atomic(current,data)
        except Exception:
            # Roll back only our own new seed, never repair an existing profile.
            present=_unlinked(seed_path).stat()
            if (not _unlinked(current).exists() and
                (present.st_dev,present.st_ino)==(created.st_dev,created.st_ino) and
                _read(seed_path,factory=True)==data):
                seed_path.unlink()
            raise
        return load(directory)


def save(directory,data,*,expected_sha256):
    """Commit a complete caller image only if its loaded predecessor is current."""
    if not isinstance(data,bytes) or len(data)!=SIZE:
        raise ValueError('CMOS save requires exactly 16384 immutable bytes')
    directory=_unlinked(directory)
    with _writer(directory):
        previous=load(directory)
        if hashlib.sha256(previous).hexdigest()!=expected_sha256:
            raise ValueError('CMOS profile changed since load; save rejected')
        _atomic(directory/'cmos.bin',data)
    return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',type=Path,required=True,help='explicit isolated profile directory')
    parser.add_argument('--prepare',action='store_true',help='initialize empty directory from authenticated factory seed')
    args=parser.parse_args()
    data=prepare(args.profile) if args.prepare else load(args.profile)
    print(json.dumps({'scope':'mk2-native-profile-storage','profile':str(args.profile.absolute()),
        'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'factory_seed_sha256':FACTORY_SHA256,
        'native_runtime_connected':False,'gameplay_complete':False}))
    return 0


if __name__=='__main__':raise SystemExit(main())
