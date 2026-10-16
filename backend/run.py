"""Start the backend: python run.py"""
import sys

import uvicorn

from app.config import Settings
from app.main import create_app

settings = Settings.from_env()
tls = bool(settings.ssl_certfile and settings.ssl_keyfile)
exposed = settings.host in {"0.0.0.0", "::"}

if exposed and (settings.token_was_generated or not tls):
    # Never serve the device-control API on the network without a fixed secret and TLS.
    sys.exit("Refusing to listen on all interfaces without ACCESS_TOKEN in .env and SSL_CERTFILE/SSL_KEYFILE.")
if settings.token_was_generated:
    print(f"\n  ACCESS_TOKEN (generated for this run; set it in .env to keep it): {settings.access_token}\n")

uvicorn.run(
    create_app(settings), host=settings.host, port=settings.port,
    ssl_certfile=settings.ssl_certfile or None, ssl_keyfile=settings.ssl_keyfile or None,
)
