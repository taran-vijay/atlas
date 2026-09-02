from atlas.app import _create_assistant


def test_desktop_module_exposes_assistant_factory() -> None:
    assert callable(_create_assistant)
