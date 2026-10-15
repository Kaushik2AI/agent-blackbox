"""Print or write the tool JSON Schemas (the committed contract lives in
packages/contracts/tools.v1.json; a test fails if code and contract drift).

    python -m agent_harness.schemas            # print
    python -m agent_harness.schemas --write    # regenerate the committed file
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_harness.tools import tool_json_schemas

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "tools.v1.json"


def render() -> str:
    return json.dumps(tool_json_schemas(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    if "--write" in sys.argv:
        CONTRACT_PATH.write_text(render())
        print(f"wrote {CONTRACT_PATH}")
    else:
        sys.stdout.write(render())


if __name__ == "__main__":
    main()
