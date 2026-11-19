"""Verify the frozen candidate and optionally evaluate an independently labeled batch."""

import argparse
from hashlib import file_digest, sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
HASHES = ROOT / "files_sha256.json"
SCRIPTS = ROOT / "candidates/evidence35/scripts"


def verify_snapshot():
    expected = json.loads(HASHES.read_text(encoding="utf-8"))
    actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*")
              if path.is_file() and path != HASHES}
    if actual != set(expected):
        raise ValueError(f"Frozen file inventory differs: {sorted(actual ^ set(expected))}")
    for name, checksum in expected.items():
        with (ROOT / name).open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != checksum:
                raise ValueError(f"Frozen file changed: {name}")
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--batch", type=Path, help="JSON file containing labeled records")
    parser.add_argument("--output", type=Path, help="New results file outside the snapshot")
    args = parser.parse_args()
    if args.batch and (not args.output or args.output.resolve().is_relative_to(ROOT)):
        parser.error("--batch requires an --output path outside the snapshot")
    if args.output and args.output.exists():
        raise FileExistsError(args.output)

    manifest = verify_snapshot()
    if args.verify:
        print(f"Verified {manifest['version']}")
        return

    batch = args.batch.read_bytes()
    rows = json.loads(batch)["records"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("The batch must contain a nonempty records list")

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPTS))
    from evaluate_targeted_v4 import CHECKS, PilotReplay, measure, normalize, with_targeted_v4

    if list(CHECKS) != [addon["id"] for addon in manifest["enabled_add_ons"]]:
        raise ValueError("Frozen add-on order differs from the manifest")
    pilot = PilotReplay()
    if pilot.verifier.cutoff != manifest["global_verifier_cutoff"]:
        raise ValueError("Frozen verifier cutoff differs from the manifest")

    descriptions = [row["description"] for row in rows]
    baseline = pilot.predict(descriptions)
    decisions = []
    for row, text, codes in zip(rows, descriptions, baseline, strict=True):
        findings, _ = with_targeted_v4(text, codes, normalize)
        decisions.append({**row, "predicted_codes": sorted(findings)})
    result = {
        "version": manifest["version"],
        "snapshot_sha256": sha256(HASHES.read_bytes()).hexdigest(),
        "batch_sha256": sha256(batch).hexdigest(),
        "metrics": measure(decisions, "predicted_codes"),
        "decisions": decisions,
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, ensure_ascii=False)
        output.write("\n")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
