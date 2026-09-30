#!/usr/bin/env bash
# Remove TUF Control. With --system, also remove the privileged helper.
set -euo pipefail
APP=io.github.erfanium.TufControl

rm -f ~/.local/bin/tuf-control \
      ~/.local/share/applications/$APP.desktop \
      ~/.local/share/icons/hicolor/scalable/apps/$APP.svg
update-desktop-database -q ~/.local/share/applications 2>/dev/null || true
echo "removed launcher (settings kept in ~/.config/tuf-control)"

if [[ "${1:-}" == "--system" ]]; then
    sudo rm -f /usr/local/libexec/tuf-control-helper /usr/share/polkit-1/actions/$APP.policy
    echo "removed privileged helper"
fi
