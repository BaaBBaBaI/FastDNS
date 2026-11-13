#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="auto"
ACTION="install"
CUSTOM_PREFIX=""

usage() {
    cat <<EOF
FastDNS Linux Installer

Usage:
  ./install_linux.sh [OPTIONS]

Options:
  --user           Install for current user (~/.local/share/fastdns)
  --system         Install system-wide (/opt/fastdns, requires root/sudo)
  --prefix DIR     Install under custom prefix DIR
  --uninstall      Uninstall FastDNS
  -h, --help       Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)
            MODE="user"
            shift
            ;;
        --system)
            MODE="system"
            shift
            ;;
        --prefix)
            if [[ $# -lt 2 ]]; then
                echo "Error: --prefix requires a directory argument." >&2
                exit 1
            fi
            MODE="custom"
            CUSTOM_PREFIX="$2"
            shift 2
            ;;
        --uninstall)
            ACTION="uninstall"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

if [[ "$MODE" == "auto" ]]; then
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        MODE="system"
    else
        MODE="user"
    fi
fi

if [[ "$MODE" == "system" ]]; then
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        echo "System-wide installation requires root. Re-run with: sudo $0 --system" >&2
        exit 1
    fi
    INSTALL_DIR="/opt/fastdns"
    BIN_DIR="/usr/local/bin"
    DESKTOP_DIR="/usr/share/applications"
elif [[ "$MODE" == "custom" ]]; then
    INSTALL_DIR="${CUSTOM_PREFIX}/share/fastdns"
    BIN_DIR="${CUSTOM_PREFIX}/bin"
    DESKTOP_DIR="${CUSTOM_PREFIX}/share/applications"
else
    INSTALL_DIR="${HOME}/.local/share/fastdns"
    BIN_DIR="${HOME}/.local/bin"
    DESKTOP_DIR="${HOME}/.local/share/applications"
fi

LAUNCHER_PATH="${BIN_DIR}/fastdns"
DESKTOP_PATH="${DESKTOP_DIR}/fastdns.desktop"

if [[ "$ACTION" == "uninstall" ]]; then
    echo "Uninstalling FastDNS from ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
    rm -f "${LAUNCHER_PATH}"
    rm -f "${DESKTOP_PATH}"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
    fi
    echo "FastDNS has been uninstalled."
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed. Please install Python 3 first." >&2
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "Warning: Python tkinter module is not installed. The GUI requires python3-tk."
    echo "Install it on Ubuntu/Debian/Mint with: sudo apt install python3-tk"
fi

echo "Installing FastDNS to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}" "${BIN_DIR}" "${DESKTOP_DIR}"

rm -rf "${INSTALL_DIR}/fastdns" "${INSTALL_DIR}/dns_profiles" "${INSTALL_DIR}/img"
cp -r "${SCRIPT_DIR}/fastdns" "${INSTALL_DIR}/fastdns"
cp -r "${SCRIPT_DIR}/dns_profiles" "${INSTALL_DIR}/dns_profiles"
mkdir -p "${INSTALL_DIR}/img"
cp -r "${SCRIPT_DIR}/img/icons" "${INSTALL_DIR}/img/icons"
cp "${SCRIPT_DIR}/main.py" "${INSTALL_DIR}/main.py"
chmod +x "${INSTALL_DIR}/main.py"

# Remove __pycache__ from installed copy
find "${INSTALL_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

cat > "${LAUNCHER_PATH}" <<EOF
#!/usr/bin/env bash
exec python3 "${INSTALL_DIR}/main.py" "\$@"
EOF
chmod +x "${LAUNCHER_PATH}"

cat > "${DESKTOP_PATH}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=FastDNS
Comment=Minimalist conditional DNS switcher for MagicDNS and custom profiles
Exec=${LAUNCHER_PATH}
Path=${INSTALL_DIR}
Icon=${INSTALL_DIR}/img/icons/dns_icon_glass_8x.png
Terminal=false
Categories=Network;Utility;
StartupNotify=true
StartupWMClass=Fastdns
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
fi

echo ""
echo "FastDNS installed successfully."
echo "  Install directory : ${INSTALL_DIR}"
echo "  Command launcher  : ${LAUNCHER_PATH}"
echo "  Desktop entry     : ${DESKTOP_PATH}"
echo ""
if [[ "$MODE" == "user" ]] && [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    echo "Note: ${BIN_DIR} is not in your PATH. Add it to ~/.bashrc or run:"
    echo "  ${LAUNCHER_PATH}"
else
    echo "Run 'fastdns' from your terminal or launch FastDNS from your application menu."
fi
