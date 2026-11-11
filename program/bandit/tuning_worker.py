"""Disposable local simulation worker; no credentials or database writes."""

import json
import os
import sys
from pathlib import Path

from .tuning import TuningConfig, evaluate


def main():
    request, destination = map(Path, sys.argv[1:])
    job = json.loads(request.read_text())
    result = evaluate(job['stats'], job['remaining'], job['baseline'], TuningConfig(**job['config']))
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, allow_nan=False))
    os.replace(temporary, destination)


if __name__ == '__main__':
    main()
