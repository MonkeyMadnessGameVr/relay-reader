"""Create a clean GitHub-upload folder and ZIP from an explicit file allowlist.

Run: python scripts/package_render.py. No local environments or secrets are copied.
"""
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
output = root / "dist" / "relay-render"
output.mkdir(parents=True, exist_ok=True)
files = [root / name for name in ("app.py", "config.py", "requirements.txt", "render.yaml",
                                  ".python-version", ".gitignore", "README.md", "RENDER_SETUP.md")]
for folder in ("templates", "static"):
    files.extend(path for path in (root / folder).rglob("*") if path.is_file())
files.append(root / "tests" / "test_gateway.py")
files.append(root / "tests" / "render_smoke.py")
files.append(Path(__file__).resolve())
archive = root / "dist" / "Relay-Render.zip"
with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zipped:
    for source in sorted(files):
        relative = source.relative_to(root)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        zipped.write(source, str(Path("relay-render") / relative))
print("Upload folder: {}".format(output))
print("Archive: {} ({} files)".format(archive, len(files)))
