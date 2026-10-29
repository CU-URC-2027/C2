"""One explicit compatibility boundary for the existing standalone modules."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "c2_prototype"))

from core import Control, JOINTS  # noqa: E402
from rover_link import RoverLink  # noqa: E402
from mock_rover import MockRover  # noqa: E402
from gps_input import GPSData, nmea_sentence  # noqa: E402
from navigation import integrate_pose, local_enu, metrics, compare_log  # noqa: E402
