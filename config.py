import os
from types import SimpleNamespace

settings = SimpleNamespace(
    NEST_CLIENT_SECRET_JSON=os.getenv("NEST_CLIENT_SECRET_JSON"),
    NEST_TOKEN_JSON=os.getenv("NEST_TOKEN_JSON"),
    NEST_DRIVE_FOLDER_ID=os.getenv("NEST_DRIVE_FOLDER_ID"),
    NEST_MAX_FILES=int(os.getenv("NEST_MAX_FILES", 5)),
    NEST_TTL_SECS=int(os.getenv("NEST_TTL_SECS", 3600)),
)
