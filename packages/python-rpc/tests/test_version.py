"""Version metadata tests for penguin-prpc."""

from penguin_prpc import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"
