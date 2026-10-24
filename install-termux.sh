#!/data/data/com.termux/files/usr/bin/bash
# Run with bash install-termux.sh if executable mode is not preserved.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${PREFIX:-}" || "${PREFIX}" != /data/data/com.termux/files/usr* ]]; then
    echo "This installer is for Termux; use python -m pip install -e . on desktop." >&2
    exit 2
fi
command -v python >/dev/null || { echo "Install Python: pkg install python" >&2; exit 2; }
echo "Installing Termux-Kivy (no Kivy/SDL dependency)..."
python -c "import setuptools" 2>/dev/null || python -m pip install "setuptools>=61"
python -m pip install --no-build-isolation -e "$ROOT"
python -m pip install 'termuxgui>=0.1.5'
python - <<'PY'
from termux_kivy import App, Button, TermuxBackend
print("Python UI runtime imported successfully.")
try:
    import termuxgui
    print("Termux:GUI Python binding installed; the Android plugin must also be installed.")
except ImportError as exc:
    raise SystemExit("Termux:GUI binding unavailable: " + str(exc))
PY
echo "Try: python $ROOT/examples/counter.py"
