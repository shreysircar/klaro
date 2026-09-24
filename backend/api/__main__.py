"""python -m backend.api — binds the port first so the real one (KLARO_PORT=0 means any free port)
can be printed as `KLARO_PORT=<n>` for Electron before uvicorn starts serving."""

import socket

import uvicorn

from backend import config
from backend.api.app import app

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind((config.HOST, config.PORT))
print(f"KLARO_PORT={sock.getsockname()[1]}", flush=True)
uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
