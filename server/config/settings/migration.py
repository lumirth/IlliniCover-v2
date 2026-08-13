import os

os.environ.setdefault("DATABASE_MODE", "direct")

from .production import *  # noqa: E402,F403
