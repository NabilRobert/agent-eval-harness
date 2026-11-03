"""A tripwire on the MCP-backbone commit the local repro is built from.

`repro/setup_repro.py` runs inside the repro image against MCP-backbone's
own scripts, so CI can't import or call them. It calls `seed(...)` with
positional arguments, the form MCP-backbone had at the pinned commit.
MCP-backbone's 3f5ae59 changed `seed` to take one `WorkspaceSpec`, so
moving the pin past it breaks the setup only when someone builds the image.
This test fails as soon as the pin changes, so the call is checked then."""

import re

from agent_eval import REPO_ROOT

# The commit setup_repro.py's calls were last checked against.
PINNED_MCP_BACKBONE_COMMIT = "4e418e915693ca5a2eba52d469cd4e009988e096"


def read_mcp_backbone_pin() -> str:
    dockerfile = (REPO_ROOT / "repro" / "Dockerfile").read_text()
    match = re.search(r"^ARG MCP_BACKBONE_COMMIT=(\S+)$", dockerfile, re.MULTILINE)
    assert match, "repro/Dockerfile has no `ARG MCP_BACKBONE_COMMIT=` line"
    return match.group(1)


def test_moving_the_mcp_backbone_pin_means_rechecking_the_setup_script() -> None:
    assert read_mcp_backbone_pin() == PINNED_MCP_BACKBONE_COMMIT, (
        "repro/Dockerfile's MCP-backbone pin moved. Check every MCP-backbone call in "
        "repro/setup_repro.py against the new commit: past 3f5ae59, `seed` takes a "
        "WorkspaceSpec (app/auth/workspaces.py) with created_via='operator', not "
        "positional arguments. Rebuild the repro image to prove it, then update "
        "PINNED_MCP_BACKBONE_COMMIT here."
    )
