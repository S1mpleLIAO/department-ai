"""No Docker group: non-root acceptance uses only a fixed root-owned launcher."""
import os
from pathlib import Path
HELPER="/usr/local/libexec/department-identity-acceptance/client.py"
def command(*args):
    if os.geteuid()==0:
        return ["docker",*args]  # Existing root-run isolated test harnesses.
    if os.geteuid()!=10001 or not Path(HELPER).is_file():
        raise RuntimeError("Restricted container launcher is not installed")
    return ["/usr/bin/python3","-I",HELPER,*args]
