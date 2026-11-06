Linux DEV launch

Run `bash ./scripts/linux/launch-dev.sh` from any directory. The script resolves the checkout from its own location, writes diagnostic logs under `desktop/logs/`, and uses only this checkout's Electron and Python environment.

Before the first launch, create `desktop/.venv` with CPython 3.12 and install `phase2g/requirements.lock` plus `desktop/requirements-build.lock`; run `npm ci` in `desktop/`. The launcher does not download runtimes or dependencies.
