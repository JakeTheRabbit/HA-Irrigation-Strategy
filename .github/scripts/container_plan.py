"""Plan one run of the controller image workflow (container.yml), or refuse it.

A candidate (a pre-release) is built once; stable only re-tags that build, and only once the
release is no longer a pre-release and `main` is at its tag. The version always equals the tag,
config.yaml and manifest.json, and each architecture's base is build.yaml's. Reads the checkout
at the tag and the release through `gh api`; changes nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

ADDON = Path("addons/f2_control")
MANIFEST = Path("custom_components/crop_steering/manifest.json")
ARCHES = ("amd64", "aarch64")  # GHCR carries no armv7 image; armv7 stays an on-box app build


class Refused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def plan(tag, channel, owner, config_yaml, manifest_json, build_yaml, release, main_sha, tag_sha):
    require(channel in ("candidate", "stable"), f"Unknown channel {channel!r}.")
    match = re.fullmatch(r"v((\d+\.\d+)\.\d+)", tag)
    require(match, f"{tag!r} is not a vX.Y.Z tag.")
    version, minor = match.groups()
    app = re.search(r'^version:\s*"?([^"\s]+)"?\s*$', config_yaml, re.M)
    require(app and app.group(1) == version, f"config.yaml version is not {version}.")
    require(json.loads(manifest_json).get("version") == version, f"manifest.json version is not {version}.")
    bases = dict(re.findall(r"^\s+(\w+):\s*(\S+)\s*$", build_yaml, re.M))
    require(all(bases.get(arch) for arch in ARCHES), "build.yaml lacks an amd64 or aarch64 base.")
    require(not release.get("draft"), f"{tag} is a draft release.")
    if channel == "candidate":
        require(release.get("prerelease"), f"{tag} is not a pre-release; only a candidate is built.")
    else:
        require(not release.get("prerelease"), f"{tag} is still a pre-release; it was not promoted.")
        require(main_sha == tag_sha, f"main is not at {tag}; only the promoted commit is stable.")
    return {
        "version": version,
        "minor": minor,
        "channel": channel,
        "image": f"ghcr.io/{owner.lower()}/crop-steering-controller",
        **{f"{arch}_from": bases[arch] for arch in ARCHES},
    }


def gh(repo, path):
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/{path}"], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out)


def main():
    repo, tag, channel = os.environ["GITHUB_REPOSITORY"], os.environ["TAG"], os.environ["CHANNEL"]
    try:
        result = plan(
            tag,
            channel,
            repo.split("/")[0],
            (ADDON / "config.yaml").read_text(encoding="utf-8"),
            MANIFEST.read_text(encoding="utf-8"),
            (ADDON / "build.yaml").read_text(encoding="utf-8"),
            gh(repo, f"releases/tags/{tag}"),
            gh(repo, "commits/main")["sha"],
            gh(repo, f"commits/{tag}")["sha"],
        )
    except Refused as error:
        print(f"::error::{error}")
        return 1
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.writelines(f"{key}={value}\n" for key, value in result.items())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
