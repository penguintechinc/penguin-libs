"""Tests for license validation decorators."""

import asyncio
import pytest
from penguin_licensing.decorators import license_required, feature_required


class TestLicenseRequiredDecorator:
    """Tests for license_required decorator."""

    @pytest.mark.asyncio
    async def test_license_required_allows_sync(self):
        """license_required wraps sync function into awaitable."""
        @license_required()
        def sync_func(x):
            return x * 2

        result = await sync_func(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_license_required_allows_async(self):
        """license_required allows async function to execute."""
        @license_required()
        async def async_func(x):
            return x * 2

        result = await async_func(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_license_required_with_tier(self):
        """license_required accepts tier argument."""
        @license_required("professional")
        async def tier_func(x):
            return x * 2

        result = await tier_func(5)
        assert result == 10

    def test_license_required_preserves_name(self):
        """license_required preserves function name."""
        @license_required()
        def my_function():
            pass

        assert my_function.__name__ == "my_function"


class TestFeatureRequiredDecorator:
    """Tests for feature_required decorator."""

    @pytest.mark.asyncio
    async def test_feature_required_allows_sync(self):
        """feature_required wraps sync function into awaitable."""
        @feature_required("sso")
        def sync_func(x):
            return x * 3

        result = await sync_func(4)
        assert result == 12

    @pytest.mark.asyncio
    async def test_feature_required_allows_async(self):
        """feature_required allows async function to execute."""
        @feature_required("sso")
        async def async_func(x):
            return x * 3

        result = await async_func(4)
        assert result == 12

    def test_feature_required_preserves_name(self):
        """feature_required preserves function name."""
        @feature_required("sso")
        def my_feature_function():
            pass

        assert my_feature_function.__name__ == "my_feature_function"
