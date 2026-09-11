"""Build/Compose wrapper using the package VERSION as the only version source."""

import argparse
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "build", "compose"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    version = (ROOT / "node_rpc_checker" / "VERSION").read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        parser.error("VERSION must be a three-component numeric release")
    if args.command == "version":
        print(version)
        return 0
    env = {**os.environ, "CHECKER_VERSION": version}
    if args.command == "build":
        if args.arguments:
            parser.error("build accepts no overrides; edit VERSION instead")
        command = [
            "docker",
            "build",
            "--build-arg",
            f"VERSION={version}",
            "-t",
            f"svetekllc/node-rpc-checker:{version}",
            ".",
        ]
    else:
        command = ["docker", "compose", *args.arguments]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
