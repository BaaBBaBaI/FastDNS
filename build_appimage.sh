#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ARCH="$(uname -m)"
APPDIR="${SCRIPT_DIR}/build/AppDir"
DIST_DIR="${SCRIPT_DIR}/dist"
OUTPUT_APPIMAGE="${DIST_DIR}/FastDNS-${ARCH}.AppImage"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required to build the AppImage." >&2
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "Error: Python tkinter module is required (e.g. sudo apt install python3-tk)." >&2
    exit 1
fi

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "Error: PyInstaller is not installed for python3." >&2
    echo "Install it with: python3 -m pip install pyinstaller" >&2
    exit 1
fi

APPIMAGETOOL_BIN="${APPIMAGETOOL:-}"
if [[ -z "${APPIMAGETOOL_BIN}" ]]; then
    if command -v appimagetool >/dev/null 2>&1; then
        APPIMAGETOOL_BIN="$(command -v appimagetool)"
    elif command -v appimagetool-x86_64.AppImage >/dev/null 2>&1; then
        APPIMAGETOOL_BIN="$(command -v appimagetool-x86_64.AppImage)"
    fi
fi

if [[ -z "${APPIMAGETOOL_BIN}" ]]; then
    echo "Error: appimagetool was not found in PATH." >&2
    echo "Download appimagetool-${ARCH}.AppImage from https://github.com/AppImage/appimagetool/releases" >&2
    echo "and either place it in PATH as 'appimagetool' or set APPIMAGETOOL=/path/to/appimagetool." >&2
    exit 1
fi

echo "Building standalone FastDNS binary with PyInstaller..."
python3 -m PyInstaller --noconfirm --clean fastdns.spec

if [[ ! -f "${DIST_DIR}/FastDNS" ]]; then
    echo "Error: Expected PyInstaller binary at ${DIST_DIR}/FastDNS was not produced." >&2
    exit 1
fi

echo "Assembling AppDir at ${APPDIR}..."
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

cp "${DIST_DIR}/FastDNS" "${APPDIR}/usr/bin/FastDNS"
chmod +x "${APPDIR}/usr/bin/FastDNS"

cp "${SCRIPT_DIR}/img/icons/dns_icon_glass_8x.png" "${APPDIR}/fastdns.png"
cp "${SCRIPT_DIR}/img/icons/dns_icon_glass_8x.png" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/fastdns.png"
ln -sf "fastdns.png" "${APPDIR}/.DirIcon"

cat > "${APPDIR}/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${HERE}/usr/bin/FastDNS" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

cat > "${APPDIR}/fastdns.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=FastDNS
Comment=Minimalist conditional DNS switcher for MagicDNS and custom profiles
Exec=FastDNS
Icon=fastdns
Terminal=false
Categories=Network;Utility;
StartupNotify=false
StartupWMClass=Fastdns
EOF

echo "Packaging ${OUTPUT_APPIMAGE}..."
ARCH="${ARCH}" "${APPIMAGETOOL_BIN}" "${APPDIR}" "${OUTPUT_APPIMAGE}"
chmod +x "${OUTPUT_APPIMAGE}"

echo ""
echo "Built standalone AppImage: ${OUTPUT_APPIMAGE}"
echo "Run it directly or install it with:"
echo "  ./install_linux.sh --appimage \"${OUTPUT_APPIMAGE}\""
