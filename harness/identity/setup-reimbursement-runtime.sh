#!/usr/bin/env bash
# Isolated prerequisites only; does not install system packages or modify production.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
/usr/bin/python3 -c 'import docx, uno, lxml'
test -x /usr/bin/libreoffice
docker image inspect pgvector/pgvector:0.8.6-pg17-bookworm >/dev/null
FONT_DIR="$ROOT/.identity-state/reimbursement-fonts"
mkdir -p "$FONT_DIR"
if [[ ! -f "$FONT_DIR/extracted/usr/share/fonts/truetype/arphic/uming.ttc" ]]; then
  cd "$FONT_DIR"
  apt-get download fonts-arphic-uming=0.2.20080216.2-10ubuntu2
  dpkg-deb -x fonts-arphic-uming_0.2.20080216.2-10ubuntu2_all.deb extracted
fi
cat > "$FONT_DIR/fonts.conf" <<'XML'
<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><include>/etc/fonts/fonts.conf</include><dir>/department-fonts</dir><cachedir>/tmp/fontconfig</cachedir></fontconfig>
XML
chmod 644 "$FONT_DIR/fonts.conf"
echo "Reimbursement dependencies ready in isolated workspace"
