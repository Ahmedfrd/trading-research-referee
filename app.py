"""Entry point: `streamlit run app.py` launches the Replicator v2 app.

The v0 competition app is kept as `app_v0.py` for reference.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "replicator" / "ui" / "app.py"), run_name="__main__")
