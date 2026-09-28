"""Build an architecture-independent deb using the target Ubuntu's dpkg-deb."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ubuntu", required=True, choices=("22.04", "24.04", "26.04"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    version = re.search(r'__version__ = "([0-9.]+)"', (root / "hdu_seat/__init__.py").read_text()).group(1)
    package_version = f"{version}-1ubuntu{args.ubuntu}"
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hdu-deb-") as temporary:
        staging = Path(temporary)

        def write(relative: str, content: str, mode: int = 0o644) -> None:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            target.chmod(mode)

        for source in sorted((root / "hdu_seat").rglob("*")):
            if source.is_file() and source.suffix in {".py", ".html"}:
                write("usr/lib/hdu-library-seat/" + source.relative_to(root).as_posix(), source.read_text(encoding="utf-8"))
        write("usr/lib/hdu-library-seat/linux_launcher.py", (root / "linux_launcher.py").read_text(encoding="utf-8"))
        write("usr/bin/hdu-library-seat", '#!/bin/sh\nexec /usr/bin/python3 -B /usr/lib/hdu-library-seat/linux_launcher.py "$@"\n', 0o755)
        write("usr/share/applications/hdu-library-seat.desktop", """[Desktop Entry]
Type=Application
Name=HDU Library Seat Helper
Name[zh_CN]=杭电图书馆座位助手
Comment=Open the local library seat reservation dashboard
Comment[zh_CN]=打开本地图书馆座位预约面板
Exec=hdu-library-seat
TryExec=hdu-library-seat
Icon=applications-education
Terminal=true
Categories=Education;Utility;
Keywords=HDU;Library;Seat;
StartupNotify=false
""")
        write("usr/share/doc/hdu-library-seat/copyright", (root / "LICENSE").read_text(encoding="utf-8"))
        write("usr/share/doc/hdu-library-seat/README.md", (root / "README.md").read_text(encoding="utf-8"))
        installed_size = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file()) // 1024 + 1
        write("DEBIAN/control", f"""Package: hdu-library-seat
Version: {package_version}
Section: education
Priority: optional
Architecture: all
Maintainer: broruan <broruan@users.noreply.github.com>
Depends: python3 (>= 3.10), ca-certificates, xdg-utils
Recommends: x-terminal-emulator
Installed-Size: {installed_size}
Homepage: https://github.com/broruan/HDU_Library_Seat
Description: HDU library seat reservation helper for Ubuntu {args.ubuntu}
 Local web dashboard with seat selection and scheduled reservation.
 Starts from the application menu and opens the default web browser.
""")
        # Directory permissions must remain usable by ordinary desktop users.
        for directory in staging.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o755)
        output = dist / f"hdu-library-seat_{package_version}_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(staging), str(output)], check=True)
        subprocess.run(["dpkg-deb", "--info", str(output)], check=True)
        print(output)


if __name__ == "__main__":
    main()
