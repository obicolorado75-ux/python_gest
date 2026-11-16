#!/usr/bin/env sh
# Lancement de développement : base locale utilisateur + interface Qt.
set -e
cd "$(dirname "$0")/.."
python -m gestdepot "$@"
