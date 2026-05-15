# -*- coding: utf-8 -*-
"""environment.py — snapshot Python + library versions to environment.json."""

import sys
import platform


def capture_environment():
    """Return a dict describing the current Python/library environment.

    Written to environment.json at the start of stage 0 so that every run is
    self-documenting and can be reproduced on the same environment.
    """
    env = {
        'python_version': sys.version,
        'platform': platform.platform(),
        'packages': {},
    }
    for pkg in ('pandas', 'numpy', 'sklearn', 'scipy', 'graphviz'):
        try:
            mod = __import__(pkg)
            env['packages'][pkg] = getattr(mod, '__version__', 'unknown')
        except ImportError:
            env['packages'][pkg] = 'NOT_INSTALLED'
    return env
