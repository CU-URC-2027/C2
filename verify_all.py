"""Cross-platform pre-bench checks. Never uploads firmware or contacts a rover."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arduino-cli", default=shutil.which("arduino-cli"))
    p.add_argument("--arduino-config")
    p.add_argument("--cxx", default=shutil.which("g++"))
    p.add_argument("--skip-gui", action="store_true", help="For headless machines; reported as skipped")
    p.add_argument("--soak-seconds", type=float, default=30)
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    skipped = []
    def run(cmd):
        print("RUN:", subprocess.list2cmdline([str(x) for x in cmd]), flush=True)
        subprocess.run(cmd, cwd=root, check=True)
    run([sys.executable, "-m", "unittest", "discover", "-s", "c2_prototype", "-v"])
    if not args.skip_gui:
        run([sys.executable, "c2_prototype/gui_regression.py"])
    else:
        skipped.append("GUI")
    run([sys.executable, "c2_prototype/soak_test.py", "--seconds", str(args.soak_seconds)])
    if args.cxx:
        with tempfile.TemporaryDirectory(prefix="c2-guard-") as tmp:
            exe = Path(tmp)/"guard_test.exe"
            run([args.cxx, "-std=c++11", "-Wall", "-Wextra",
                 "c2_prototype/firmware/tests/guard_test.cpp", "-o", exe])
            run([exe])
    else:
        skipped.append("native C++ guard (supply --cxx)")
    if args.arduino_cli:
        cmd = [args.arduino_cli, "compile"]
        if args.arduino_config:
            cmd += ["--config-file", args.arduino_config]
        run(cmd+["--fqbn", "arduino:renesas_uno:unor4wifi", "c2_prototype/firmware/mini_rover_c2"])
    else:
        skipped.append("Arduino compilation (supply --arduino-cli)")
    print("Requested checks passed. Skipped:", ", ".join(skipped) or "none")
    print("Physical Wi-Fi, motor power and display timing still need a bench test.")

if __name__ == "__main__":
    main()
