"""Every module imports on its own — catches circular imports that only
show up when a module is the first one loaded (e.g. library use)."""

import pkgutil
import subprocess
import sys

import xping

MODULES = sorted(
    m.name for m in pkgutil.walk_packages(xping.__path__, "xping.") if m.name != "xping.__main__"
)


def test_every_module_imports_standalone():
    script = (
        "import importlib, sys\n"
        "failed = []\n"
        "for name in sys.argv[1:]:\n"
        "    for loaded in [k for k in sys.modules if k == 'xping' or k.startswith('xping.')]:\n"
        "        del sys.modules[loaded]\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception as exc:\n"
        "        failed.append(f'{name}: {exc!r}')\n"
        "print('\\n'.join(failed))\n"
        "sys.exit(1 if failed else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, *MODULES], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_lower_layers_do_not_import_the_cli():
    import pathlib

    root = pathlib.Path(xping.__file__).parent
    offenders = [
        str(path.relative_to(root))
        for layer in ("diagnostics", "models", "render", "exporters")
        for path in (root / layer).rglob("*.py")
        if "from xping.cli" in path.read_text(encoding="utf-8")
        or "import xping.cli" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
