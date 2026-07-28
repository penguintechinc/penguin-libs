"""Version metadata tests for penguin-rpc."""

from penguin_rpc import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"
