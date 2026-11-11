"""Collect installed versions reachable from backend requirements for auditing.

Run with the verification interpreter, not an application container with private
configuration. This reports installed fixture versions, not a resolved lockfile.
"""
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

requirements, destination = map(Path, sys.argv[1:])
pending = [Requirement(line.strip()) for line in requirements.read_text().splitlines()
           if line.strip() and not line.lstrip().startswith("#")]
seen = set()
versions, missing, incompatible = {}, [], []
while pending:
    requirement = pending.pop()
    key = canonicalize_name(requirement.name)
    signature = (key, tuple(sorted(requirement.extras)))
    if signature in seen:
        continue
    seen.add(signature)
    try:
        distribution = metadata.distribution(requirement.name)
    except metadata.PackageNotFoundError:
        missing.append(requirement.name)
        continue
    versions[key] = distribution.version
    if requirement.specifier and distribution.version not in requirement.specifier:
        incompatible.append({"package": key, "installed": distribution.version, "required": str(requirement.specifier)})
    for raw in distribution.requires or []:
        child = Requirement(raw)
        if child.marker is None or any(child.marker.evaluate({"extra": extra}) for extra in ["", *requirement.extras]):
            pending.append(child)
destination.write_text("".join(f"{name}=={version}\n" for name, version in sorted(versions.items())), encoding="utf-8")
print(json.dumps({"packages": len(versions), "missing": sorted(set(missing)), "incompatible": incompatible}, indent=2))
