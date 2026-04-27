"""Tests for pagination helpers."""

import math
from unittest.mock import MagicMock
from typing import Any

import pytest
from flask import Flask, request

from penguin_flask.pagination import get_pagination_params, paginate


class TestGetPaginationParams:
    """Tests for get_pagination_params function."""

    def test_default_parameters(self, app: Flask) -> None:
        """Test get_pagination_params with no query parameters."""
        with app.test_request_context("/"):
            page, per_page = get_pagination_params()

        assert page == 1
        assert per_page == 20

    def test_custom_default_per_page(self, app: Flask) -> None:
        """Test get_pagination_params with custom default_per_page."""
        with app.test_request_context("/"):
            page, per_page = get_pagination_params(default_per_page=50)

        assert page == 1
        assert per_page == 50

    def test_with_page_in_query_string(self, app: Flask) -> None:
        """Test extracting page from query string."""
        with app.test_request_context("/?page=2"):
            page, per_page = get_pagination_params()

        assert page == 2
        assert per_page == 20

    def test_with_per_page_in_query_string(self, app: Flask) -> None:
        """Test extracting per_page from query string."""
        with app.test_request_context("/?per_page=50"):
            page, per_page = get_pagination_params()

        assert page == 1
        assert per_page == 50

    def test_with_both_params_in_query_string(self, app: Flask) -> None:
        """Test extracting both page and per_page from query string."""
        with app.test_request_context("/?page=3&per_page=25"):
            page, per_page = get_pagination_params()

        assert page == 3
        assert per_page == 25

    def test_page_zero_becomes_one(self, app: Flask) -> None:
        """Test that page=0 defaults to page=1."""
        with app.test_request_context("/?page=0"):
            page, per_page = get_pagination_params()

        assert page == 1

    def test_negative_page_becomes_one(self, app: Flask) -> None:
        """Test that negative page defaults to 1."""
        with app.test_request_context("/?page=-5"):
            page, per_page = get_pagination_params()

        assert page == 1

    def test_per_page_zero_becomes_one(self, app: Flask) -> None:
        """Test that per_page=0 is treated as 1 (max(1, 0) = 1)."""
        with app.test_request_context("/?per_page=0"):
            page, per_page = get_pagination_params(default_per_page=20)

        assert per_page == 1

    def test_negative_per_page_becomes_one(self, app: Flask) -> None:
        """Test that negative per_page is treated as 1 (max(1, -10) = 1)."""
        with app.test_request_context("/?per_page=-10"):
            page, per_page = get_pagination_params(default_per_page=20)

        assert per_page == 1

    def test_invalid_page_string(self, app: Flask) -> None:
        """Test that non-numeric page defaults to 1."""
        with app.test_request_context("/?page=invalid"):
            page, per_page = get_pagination_params()

        assert page == 1

    def test_invalid_per_page_string(self, app: Flask) -> None:
        """Test that non-numeric per_page defaults to default_per_page."""
        with app.test_request_context("/?per_page=invalid"):
            page, per_page = get_pagination_params(default_per_page=20)

        assert per_page == 20

    def test_both_invalid(self, app: Flask) -> None:
        """Test handling of both invalid page and per_page."""
        with app.test_request_context("/?page=abc&per_page=xyz"):
            page, per_page = get_pagination_params(default_per_page=30)

        assert page == 1
        assert per_page == 30

    def test_float_page_invalid_string(self, app: Flask) -> None:
        """Test that float string page values are treated as invalid and default to 1."""
        with app.test_request_context("/?page=2.7"):
            page, per_page = get_pagination_params()

        # Float strings like "2.7" fail int() conversion, so default to 1
        assert page == 1
        assert isinstance(page, int)

    def test_float_per_page_invalid_string(self, app: Flask) -> None:
        """Test that float string per_page values are treated as invalid and default."""
        with app.test_request_context("/?per_page=25.3"):
            page, per_page = get_pagination_params()

        # Float strings like "25.3" fail int() conversion, so default to default_per_page (20)
        assert per_page == 20
        assert isinstance(per_page, int)

    def test_large_page_number(self, app: Flask) -> None:
        """Test handling of very large page numbers."""
        with app.test_request_context("/?page=999999"):
            page, per_page = get_pagination_params()

        assert page == 999999

    def test_large_per_page(self, app: Flask) -> None:
        """Test handling of very large per_page values."""
        with app.test_request_context("/?per_page=10000"):
            page, per_page = get_pagination_params()

        assert per_page == 10000

    def test_whitespace_in_params(self, app: Flask) -> None:
        """Test handling of whitespace in parameters."""
        with app.test_request_context("/?page=%202%20"):
            page, per_page = get_pagination_params()

        # Query string decoding handles whitespace
        assert page >= 1


class TestPaginateWithList:
    """Tests for paginate function with plain lists."""

    def test_paginate_empty_list(self) -> None:
        """Test paginating an empty list."""
        result = paginate([], page=1, per_page=20)

        assert result["items"] == []
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert result["total"] == 0
        assert result["pages"] == 0

    def test_paginate_single_item(self) -> None:
        """Test paginating a list with one item."""
        data = [{"id": 1}]
        result = paginate(data, page=1, per_page=20)

        assert result["items"] == data
        assert result["total"] == 1
        assert result["pages"] == 1

    def test_paginate_first_page(self) -> None:
        """Test first page of results."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=1, per_page=5)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 1
        assert result["items"][4]["id"] == 5
        assert result["page"] == 1
        assert result["total"] == 10
        assert result["pages"] == 2

    def test_paginate_second_page(self) -> None:
        """Test second page of results."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=2, per_page=5)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 6
        assert result["items"][4]["id"] == 10
        assert result["page"] == 2

    def test_paginate_last_page_partial(self) -> None:
        """Test last page with fewer items than per_page."""
        data = [{"id": i} for i in range(1, 26)]  # 25 items
        result = paginate(data, page=3, per_page=10)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 21
        assert result["total"] == 25
        assert result["pages"] == 3

    def test_paginate_out_of_bounds_page(self) -> None:
        """Test requesting a page beyond available data."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=10, per_page=5)

        assert result["items"] == []
        assert result["page"] == 10
        assert result["total"] == 5
        assert result["pages"] == 1

    def test_paginate_page_zero_becomes_one(self) -> None:
        """Test that page 0 is treated as page 1."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=0, per_page=5)

        assert result["items"][0]["id"] == 1
        assert result["page"] == 1

    def test_paginate_negative_page_becomes_one(self) -> None:
        """Test that negative page is treated as page 1."""
        data = [{"id": i} for i in range(1, 11)]
        result = paginate(data, page=-5, per_page=5)

        assert result["items"][0]["id"] == 1
        assert result["page"] == 1

    def test_paginate_per_page_zero_becomes_one(self) -> None:
        """Test that per_page=0 is treated as 1."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=0)

        assert len(result["items"]) == 1
        assert result["per_page"] == 1
        assert result["pages"] == 5

    def test_paginate_negative_per_page_becomes_one(self) -> None:
        """Test that negative per_page is treated as 1."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=-10)

        assert len(result["items"]) == 1
        assert result["per_page"] == 1

    def test_paginate_all_on_one_page(self) -> None:
        """Test when all items fit on one page."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=100)

        assert len(result["items"]) == 5
        assert result["pages"] == 1

    def test_paginate_string_items(self) -> None:
        """Test paginating a list of strings."""
        data = ["apple", "banana", "cherry", "date", "elderberry"]
        result = paginate(data, page=1, per_page=2)

        assert result["items"] == ["apple", "banana"]
        assert result["total"] == 5
        assert result["pages"] == 3

    def test_paginate_mixed_types(self) -> None:
        """Test paginating a list with mixed types."""
        data = [1, "two", 3.0, {"four": 4}, [5]]
        result = paginate(data, page=1, per_page=10)

        assert result["items"] == data
        assert result["total"] == 5

    def test_paginate_pages_calculation(self) -> None:
        """Test correct calculation of total pages."""
        test_cases = [
            (10, 5, 2),   # 10 items, 5 per page = 2 pages
            (11, 5, 3),   # 11 items, 5 per page = 3 pages
            (20, 10, 2),  # 20 items, 10 per page = 2 pages
            (21, 10, 3),  # 21 items, 10 per page = 3 pages
            (100, 7, 15), # 100 items, 7 per page = 15 pages
            (1, 10, 1),   # 1 item, 10 per page = 1 page
        ]

        for total_items, per_page, expected_pages in test_cases:
            data = list(range(total_items))
            result = paginate(data, page=1, per_page=per_page)
            assert result["pages"] == expected_pages, \
                f"Failed for {total_items} items, {per_page} per page"


class TestPaginateWithQuery:
    """Tests for paginate function with SQLAlchemy-like queries."""

    def test_paginate_sqlalchemy_query(self) -> None:
        """Test paginating a mock SQLAlchemy query."""
        # Create a mock query object
        mock_query = MagicMock()
        mock_query.count.return_value = 100
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [{"id": i} for i in range(1, 21)]

        result = paginate(mock_query, page=1, per_page=20)

        assert result["total"] == 100
        assert len(result["items"]) == 20
        assert result["pages"] == 5
        mock_query.count.assert_called_once()
        mock_query.offset.assert_called_once_with(0)
        mock_query.limit.assert_called_once_with(20)

    def test_paginate_query_second_page(self) -> None:
        """Test paginating query for second page."""
        mock_query = MagicMock()
        mock_query.count.return_value = 100
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [{"id": i} for i in range(21, 41)]

        result = paginate(mock_query, page=2, per_page=20)

        assert result["page"] == 2
        mock_query.offset.assert_called_once_with(20)

    def test_paginate_query_empty_result(self) -> None:
        """Test paginating query with zero results."""
        mock_query = MagicMock()
        mock_query.count.return_value = 0
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = paginate(mock_query, page=1, per_page=20)

        assert result["total"] == 0
        assert result["items"] == []
        assert result["pages"] == 0

    def test_paginate_query_uses_offset_limit(self) -> None:
        """Test that query uses offset and limit methods."""
        mock_query = MagicMock()
        mock_query.count.return_value = 50
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        paginate(mock_query, page=3, per_page=10)

        # Page 3, 10 per page = offset 20
        mock_query.offset.assert_called_with(20)
        mock_query.limit.assert_called_with(10)


class TestPaginateListLike:
    """Tests for paginate with list-like objects (penguin-dal Rows, etc)."""

    def test_paginate_generator(self) -> None:
        """Test paginating a generator object."""
        def data_generator() -> Any:
            for i in range(1, 26):
                yield {"id": i}

        result = paginate(data_generator(), page=1, per_page=10)

        assert len(result["items"]) == 10
        assert result["total"] == 25
        assert result["pages"] == 3

    def test_paginate_tuple(self) -> None:
        """Test paginating a tuple."""
        data = tuple([{"id": i} for i in range(1, 11)])
        result = paginate(data, page=1, per_page=5)

        assert len(result["items"]) == 5
        assert result["total"] == 10

    def test_paginate_custom_iterable(self) -> None:
        """Test paginating a custom iterable."""
        class CustomIterable:
            def __init__(self, items: list[Any]) -> None:
                self.items = items

            def __iter__(self) -> Any:
                return iter(self.items)

            def __len__(self) -> int:
                return len(self.items)

        data = CustomIterable([{"id": i} for i in range(1, 21)])
        result = paginate(data, page=2, per_page=5)

        assert len(result["items"]) == 5
        assert result["items"][0]["id"] == 6


class TestPaginateResponseStructure:
    """Tests for paginate response structure and fields."""

    def test_paginate_response_has_all_fields(self) -> None:
        """Test that paginate response includes all required fields."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=20)

        required_fields = ["items", "page", "per_page", "total", "pages"]
        for field in required_fields:
            assert field in result

    def test_paginate_items_is_list(self) -> None:
        """Test that items field is always a list."""
        data = [{"id": 1}]
        result = paginate(data, page=1, per_page=20)

        assert isinstance(result["items"], list)

    def test_paginate_numeric_fields_are_integers(self) -> None:
        """Test that numeric fields are integers."""
        data = [{"id": i} for i in range(1, 6)]
        result = paginate(data, page=1, per_page=20)

        assert isinstance(result["page"], int)
        assert isinstance(result["per_page"], int)
        assert isinstance(result["total"], int)
        assert isinstance(result["pages"], int)

    def test_paginate_all_values_match_expectations(self) -> None:
        """Test that all response values match expected values."""
        data = [{"id": i} for i in range(1, 26)]
        result = paginate(data, page=2, per_page=10)

        assert result["page"] == 2
        assert result["per_page"] == 10
        assert result["total"] == 25
        assert result["pages"] == 3
        assert len(result["items"]) == 10
        assert result["items"][0]["id"] == 11

    def test_paginate_zero_total_zero_pages(self) -> None:
        """Test that total=0 results in pages=0."""
        result = paginate([], page=1, per_page=20)

        assert result["total"] == 0
        assert result["pages"] == 0
