"""Check that Hatchling and uv agree on source layout and Python version."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_source_package_is_explicit():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    paths = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert paths == ["src/vision_measurement"]
    assert (ROOT / paths[0] / "__init__.py").is_file()
    assert data["project"]["scripts"]["vmeasure"] == "vision_measurement.cli:app"


def test_default_python_version():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert (ROOT / ".python-version").read_text().strip() == "3.15"
    assert data["project"]["requires-python"] == ">=3.15,<3.16"
