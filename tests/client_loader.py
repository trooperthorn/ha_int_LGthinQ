"""Load the internal client without requiring the Home Assistant application."""
from pathlib import Path
import sys
import types
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
name = "custom_components.lg_thinq_extended"
if name not in sys.modules:
    package = types.ModuleType(name)
    package.__path__ = [str(ROOT / "custom_components/lg_thinq_extended")]
    sys.modules[name] = package
