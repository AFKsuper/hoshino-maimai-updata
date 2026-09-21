"""Core unit tests import the installed module name without booting a QQ bot.
Real Hoshino loading is tested separately by scripts/smoke_hoshino.py.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('maimai_updata')
package.__path__ = [str(ROOT)]
sys.modules.setdefault('maimai_updata', package)
