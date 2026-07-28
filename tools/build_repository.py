from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"


def find_addons() -> list[Path]:
    """Find top-level Kodi addon folders."""

    addons = []

    for folder in ROOT.iterdir():
        if not folder.is_dir():
            continue

        if folder.name.startswith(("plugin.", "repository.", "script.", "service.")):
            if (folder / "addon.xml").exists():
                addons.append(folder)

    return sorted(addons)


def read_addon_xml(addon_folder: Path) -> ET.Element:
    addon_xml = addon_folder / "addon.xml"
    root = ET.parse(addon_xml).getroot()

    addon_id = root.attrib.get("id")
    version = root.attrib.get("version")

    if not addon_id:
        raise ValueError(f"No addon ID found in {addon_xml}")

    if not version:
        raise ValueError(f"No version found in {addon_xml}")

    if addon_folder.name != addon_id:
        raise ValueError(
            f"Folder '{addon_folder.name}' does not match addon ID '{addon_id}'"
        )

    return root


def include_file(path: Path) -> bool:
    excluded_parts = {
        ".git",
        ".github",
        "__pycache__",
        ".pytest_cache",
        ".idea",
        ".vscode",
    }

    if any(part in excluded_parts for part in path.parts):
        return False

    if path.suffix.lower() in {".pyc", ".pyo"}:
        return False

    return True


def create_zip(
    addon_folder: Path,
    addon_id: str,
    version: str,
) -> Path:
    destination = PUBLIC_DIR / addon_id
    destination.mkdir(parents=True, exist_ok=True)

    zip_path = destination / f"{addon_id}-{version}.zip"

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:

        for file_path in sorted(addon_folder.rglob("*")):
            if not file_path.is_file():
                continue

            relative_path = file_path.relative_to(addon_folder)

            if not include_file(relative_path):
                continue

            archive_path = Path(addon_id) / relative_path

            archive.write(
                file_path,
                archive_path.as_posix(),
            )

    return zip_path


def copy_artwork(addon_folder: Path, addon_id: str) -> None:
    destination = PUBLIC_DIR / addon_id

    for filename in ("icon.png", "fanart.jpg", "fanart.png"):
        source = addon_folder / filename

        if source.exists():
            shutil.copy2(source, destination / filename)


def create_index_html(destination: Path, addon_id: str, version: str) -> None:
    """Create an index.html in the addon subdirectory so Kodi can browse it."""
    zip_filename = f"{addon_id}-{version}.zip"
    html = f"""<!DOCTYPE html>
<html>
<head><title>{addon_id}</title></head>
<body>
<a href="{zip_filename}">{zip_filename}</a>
</body>
</html>
"""
    (destination / "index.html").write_text(html, encoding="utf-8")


def create_addons_xml(addons: list[ET.Element]) -> bytes:
    root = ET.Element("addons")

    for addon in addons:
        root.append(addon)

    ET.indent(root, space="    ")

    return (
        ET.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )
        + b"\n"
    )


def main() -> None:
    addon_folders = find_addons()

    if not addon_folders:
        raise RuntimeError("No Kodi addon folders were found.")

    if PUBLIC_DIR.exists():
        shutil.rmtree(PUBLIC_DIR)

    PUBLIC_DIR.mkdir(parents=True)

    addon_elements = []

    for addon_folder in addon_folders:
        addon_element = read_addon_xml(addon_folder)

        addon_id = addon_element.attrib["id"]
        version = addon_element.attrib["version"]

        zip_path = create_zip(
            addon_folder,
            addon_id,
            version,
        )

        copy_artwork(addon_folder, addon_id)
        create_index_html(PUBLIC_DIR / addon_id, addon_id, version)
        addon_elements.append(addon_element)

        print(f"Created {zip_path.relative_to(ROOT)}")

    addons_xml = create_addons_xml(addon_elements)

    (PUBLIC_DIR / "addons.xml").write_bytes(addons_xml)

    checksum = hashlib.md5(addons_xml).hexdigest()

    (PUBLIC_DIR / "addons.xml.md5").write_text(
        checksum,
        encoding="utf-8",
    )

    (PUBLIC_DIR / ".nojekyll").write_text(
        "",
        encoding="utf-8",
    )

    print("Created public/addons.xml")
    print("Created public/addons.xml.md5")
    print("Repository build completed successfully.")


if __name__ == "__main__":
    main()
