#!/usr/bin/env python3
"""Verify browser, NET5 and ROS host code using synthetic/loopback tests only."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-gui", action="store_true", help="Explicitly omit desktop/ROS Tk widget checks")
    parser.add_argument("--soak-seconds", type=float, default=10)
    parser.add_argument("--cxx", default=shutil.which("g++") or shutil.which("clang++"))
    parser.add_argument("--arduino-cli", help="Opt in to compilation only; never uploads")
    parser.add_argument("--arduino-config")
    args = parser.parse_args()
    if not 1 <= args.soak_seconds <= 300:
        parser.error("--soak-seconds must be between 1 and 300")
    node = shutil.which("node")
    if not node:
        parser.error("Node.js 18+ is required for controller/video-view checks")
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv is required to verify the separate video prototype environment")

    completed, skipped = [], []

    def run(label, command, cwd=ROOT):
        print(f"\nCHECK: {label}", flush=True)
        environment = os.environ.copy()
        if cwd != ROOT:
            environment.pop("VIRTUAL_ENV", None)  # Use the prototype's own lock/environment.
        subprocess.run([str(part) for part in command], cwd=cwd, env=environment, check=True)
        completed.append(label)

    run("Browser API, runtime, priorities and video receiver", [sys.executable, "-m", "pytest", "-q"])
    run("Browser controller mapping", [node, "tests/controller_test.mjs"])
    run("Video view lifecycle", [node, "--test", "tests/video_view_test.mjs"])
    for source in sorted((ROOT/"web").iterdir()):
        if source.suffix in (".js", ".mjs"):
            run(f"JavaScript syntax: {source.name}", [node, "--check", source])
    video = ROOT/"prototypes/video_pipeline"
    run("Video prototype policy/lifecycle/protocol (no GPU or FFmpeg)",
        [uv, "run", "--frozen", "python", "-m", "pytest", "-q"], cwd=video)
    for source in sorted((video/"web").glob("*.js")):
        run(f"Prototype JavaScript syntax: {source.name}", [node, "--check", source])
    run("NET5 desktop unit/integration", [sys.executable, "-m", "unittest", "discover", "-s", "c2_prototype"])
    if args.skip_gui:
        skipped.extend(["Desktop Tk GUI", "ROS dashboard Tk widgets"])
    else:
        run("Desktop Tk GUI", [sys.executable, "c2_prototype/gui_regression.py"])

    # Run discovery through Python so this is portable to Windows without shell
    # PYTHONPATH syntax. These are host checks, not ROS/DDS execution.
    ros_tests = ROOT/"ros2_ws/src/urc_c2_chassis/test"
    ros_patterns = ["test_policy.py", "test_bridge.py"] if args.skip_gui else ["test_*.py"]
    for pattern in ros_patterns:
        run(f"ROS chassis host: {pattern}", [sys.executable, "-c",
            "import sys,unittest;sys.path.insert(0,sys.argv[1]);"
            "suite=unittest.defaultTestLoader.discover(sys.argv[2],pattern=sys.argv[3]);"
            "result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())",
            ROOT/"ros2_ws/src/urc_c2_chassis", ros_tests, pattern])
    run("NET5 delayed-reply loopback soak", [sys.executable, "c2_prototype/soak_test.py",
        "--seconds", args.soak_seconds, "--delay-ms", "150"])
    if args.cxx:
        with tempfile.TemporaryDirectory(prefix="c2-guard-") as temporary:
            binary = Path(temporary)/"guard_test.exe"
            run("Native guard compile", [args.cxx, "-std=c++11", "-Wall", "-Wextra",
                "c2_prototype/firmware/tests/guard_test.cpp", "-o", binary])
            run("Native guard tests", [binary])
    else:
        skipped.append("Native C++ guard: no compiler found")
    if args.arduino_cli:
        command = [args.arduino_cli, "compile"]
        if args.arduino_config:
            command += ["--config-file", args.arduino_config]
        run("Optional Uno R4 firmware compile", command+[
            "--fqbn", "arduino:renesas_uno:unor4wifi", "c2_prototype/firmware/mini_rover_c2"])
    else:
        skipped.append("Arduino compilation: opt in with --arduino-cli")
    print(f"\nPASS: {len(completed)} requested checks completed.")
    print("Skipped: " + ("; ".join(skipped) or "none"))
    print("Actual browser decoding, physical controllers/devices and ROS/DDS require separate acceptance tests.")


if __name__ == "__main__":
    main()
