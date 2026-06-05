"""Tests for Home Assistant and HACS icon assets."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "rideradar"


def test_integration_icon_assets_exist_at_ha_expected_paths() -> None:
    """Keep icon assets in locations used by Home Assistant/HACS UI contexts."""
    for relative_path in ("icon.svg", "logo.svg", "assets/icon.svg"):
        asset = INTEGRATION / relative_path
        assert asset.exists()
        assert asset.stat().st_size > 0


def test_icon_assets_use_visible_static_color() -> None:
    """Avoid currentColor-only SVGs that can render invisible as plain images."""
    for relative_path in ("icon.svg", "logo.svg", "assets/icon.svg"):
        svg = (INTEGRATION / relative_path).read_text(encoding="utf-8")
        assert 'stroke="#03a9f4"' in svg
        assert 'stroke="currentColor"' not in svg
