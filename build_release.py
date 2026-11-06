"""Build a clean, allowlisted plugin archive without Git history or user data."""
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = ("manifest.json", "BarWidget.qml", "jobs.py", "servicem8-icon.png",
         "monochrome.frag", "monochrome.frag.qsb", "README.md", "LICENSE",
         "build_release.py", "test_jobs.py", ".gitignore")


def build():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    version = manifest["version"]
    if not version or any(c not in "0123456789.-" for c in version):
        raise ValueError("Unsafe release version")
    for name in FILES:
        if not (ROOT / name).is_file() or (ROOT / name).is_symlink():
            raise ValueError("Missing or unsafe release file: " + name)
    output = ROOT / "dist" / ("servicem8-jobs-" + version + ".zip")
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, name)
    return output


if __name__ == "__main__":
    print(build())
