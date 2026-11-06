"""Daily discovery and proposal generation only; never approves or writes to CRM."""
import fcntl
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    (ROOT/'data').mkdir(exist_ok=True)
    with (ROOT/'data/daily.lock').open('w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another daily run is active; skipping.')
            return
        subprocess.run([sys.executable,str(ROOT/'discover.py')],cwd=ROOT,check=True)
        subprocess.run([sys.executable,str(ROOT/'reconcile.py')],cwd=ROOT,check=True)

if __name__=='__main__':main()
