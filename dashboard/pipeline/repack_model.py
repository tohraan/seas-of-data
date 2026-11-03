"""Rebuild a single best.pt from a copy that a browser or unzip tool unpacked into a folder.

A .pt file is really a zip archive, so some tools extract it. The folder holds data.pkl and a data/ folder of
numbered tensor files, which are the model's weights and not images.

  python repack_model.py ../../data/best.pt/best ../../data/model/best.pt
"""
import os
import sys
import zipfile


def main(unpacked: str, output: str) -> None:
    prefix = os.path.basename(unpacked.rstrip("/"))
    names = []
    for folder, _, files in os.walk(unpacked):
        names.extend(os.path.relpath(os.path.join(folder, name), unpacked) for name in files)
    first = ["data.pkl", ".format_version", ".storage_alignment", "byteorder"]
    rest = sorted(name for name in names if name not in first)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    # Tensors are stored uncompressed, as torch.save does. Extracted files can carry pre-1980 timestamps.
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED, allowZip64=True, strict_timestamps=False) as archive:
        for name in first + rest:
            archive.write(os.path.join(unpacked, name), f"{prefix}/{name}")
    print(f"wrote {output}: {os.path.getsize(output)} bytes, {len(first + rest)} entries")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
