"""OS-released cross-process lock for Windows local training jobs."""
from contextlib import contextmanager
from .config import STATE
@contextmanager
def exclusive(name):
    import msvcrt
    handle=(STATE/(name+'.lock')).open('a+b')
    handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
    try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        handle.close();raise ValueError('另一个进程正在执行'+name+'，请等待完成')
    try:yield
    finally:
        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1);handle.close()
