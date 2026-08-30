"""Legacy direct development launcher.

Supported host and packaged deployments use ``host_console.py`` or
``app_launcher.py``.  This convenience entry point intentionally listens only
on loopback and must not be used to expose the application to a network.
"""

import uvicorn

if __name__ == "__main__":
    print("Starting So hoa All in One development server on loopback only...")
    print("Please open your browser and navigate to: http://127.0.0.1:8000")
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True)
