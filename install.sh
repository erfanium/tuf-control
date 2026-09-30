#!/usr/bin/env bash
# Install TUF Control for the current user. With --system, also install the
# privileged helper + polkit policy so power-limit changes need no password.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
APP=io.github.erfanium.TufControl
DIR=$PWD

if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 7)' 2>/dev/null; then
    echo "error: GTK 4 + libadwaita >= 1.7 Python bindings not found." >&2
    echo "  Ubuntu/Debian: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" >&2
    echo "  Fedora:        sudo dnf install python3-gobject gtk4 libadwaita" >&2
    echo "  Arch:          sudo pacman -S python-gobject gtk4 libadwaita" >&2
    exit 1
fi
command -v asusctl >/dev/null || echo "warning: asusctl not found — see https://asus-linux.org" >&2
command -v supergfxctl >/dev/null || echo "note: supergfxctl not found — the Graphics page will be empty" >&2

mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$DIR/tuf-control" ~/.local/bin/tuf-control
sed "s|@EXEC@|$DIR/tuf-control|" data/$APP.desktop > ~/.local/share/applications/$APP.desktop
cp data/icons/hicolor/scalable/apps/$APP.svg ~/.local/share/icons/hicolor/scalable/apps/
gtk-update-icon-cache -q -t ~/.local/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q ~/.local/share/applications 2>/dev/null || true
echo "installed launcher: ~/.local/share/applications/$APP.desktop"

if [[ "${1:-}" == "--system" ]]; then
    sudo install -Dm755 data/tuf-control-helper /usr/local/libexec/tuf-control-helper
    sudo install -Dm644 data/$APP.policy /usr/share/polkit-1/actions/$APP.policy
    echo "installed privileged helper (no password prompts for PPT / curve reset)"
fi
