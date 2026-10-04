"""Allow ``python -m alphabrief_cli`` and give PyInstaller a stable entry.

The packaged backend binary executes this module; it must stay the only
place that calls the Typer application object directly.
"""

from alphabrief_cli.main import app

if __name__ == "__main__":
    app()
