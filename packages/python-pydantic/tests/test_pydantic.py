"""Comprehensive tests for penguin-pydantic module."""

import asyncio
import json
import warnings
from typing import Optional
from unittest.mock import MagicMock, Mock, patch

import pytest
from pydantic import BaseModel, ValidationError

# Flask is optional, only import if needed for tests
try:
    from flask import Flask, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    from flask_restx import Api
    FLASK_RESTX_AVAILABLE = True
except ImportError:
    FLASK_RESTX_AVAILABLE = False

from penguin_pydantic import (
    ConfigurableModel,
    Description1000,
    ElderBaseModel,
    EmailStr,
    HostnameStr,
    IPAddressStr,
    IPv4Str,
    IPv6Str,
    ImmutableModel,
    ModeratePassword,
    Name255,
    NonEmptyStr,
    RequestModel,
    ShortText100,
    SlugStr,
    StrongPassword,
    URLStr,
    ValidationErrorResponse,
    bounded_str,
    model_response,
    strong_password,
    validate_body,
    validate_query_params,
    validated_request,
)


class TestElderBaseModel:
    """Tests for ElderBaseModel class."""

    def test_basic_model_creation(self) -> None:
        """Test basic model instantiation and field access."""

        class User(ElderBaseModel):
            id: str
            name: str
            age: int

        user = User(id="123", name="John Doe", age=30)
        assert user.id == "123"
        assert user.name == "John Doe"
        assert user.age == 30

    def test_validate_assignment(self) -> None:
        """Test that validate_assignment is enabled."""

        class User(ElderBaseModel):
            age: int

        user = User(age=30)
        user.age = 31
        assert user.age == 31

        with pytest.raises(ValidationError):
            user.age = "invalid"

    def test_populate_by_name(self) -> None:
        """Test that both field names and aliases work."""

        class User(ElderBaseModel):
            user_id: str

        user = User(user_id="123")
        assert user.user_id == "123"

    def test_use_enum_values(self) -> None:
        """Test that enum values are serialized."""
        from enum import Enum

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class Profile(ElderBaseModel):
            status: Status

        profile = Profile(status=Status.ACTIVE)
        assert profile.model_dump()["status"] == "active"

    def test_from_attributes(self) -> None:
        """Test that ORM objects can be converted to model."""

        class User(ElderBaseModel):
            name: str
            email: str

        class ORMUser:
            def __init__(self, name: str, email: str) -> None:
                self.name = name
                self.email = email

        orm_user = ORMUser(name="John", email="john@example.com")
        user = User.model_validate(orm_user)
        assert user.name == "John"
        assert user.email == "john@example.com"

    def test_to_dict_basic(self) -> None:
        """Test to_dict conversion."""

        class User(ElderBaseModel):
            id: str
            name: str
            email: str

        user = User(id="123", name="John", email="john@example.com")
        result = user.to_dict()
        assert result == {"id": "123", "name": "John", "email": "john@example.com"}

    def test_to_dict_exclude_none(self) -> None:
        """Test to_dict with exclude_none=True."""

        class User(ElderBaseModel):
            id: str
            name: str
            email: Optional[str] = None

        user = User(id="123", name="John", email=None)
        result = user.to_dict(exclude_none=True)
        assert "email" not in result
        assert result == {"id": "123", "name": "John"}

    def test_to_dict_exclude_unset(self) -> None:
        """Test to_dict with exclude_unset=True."""

        class User(ElderBaseModel):
            id: str
            name: str
            email: Optional[str] = None

        user = User(id="123", name="John")
        result = user.to_dict(exclude_unset=True)
        assert "email" not in result
        assert result == {"id": "123", "name": "John"}

    def test_from_row_dict(self) -> None:
        """Test from_row with plain dictionary."""

        class User(ElderBaseModel):
            id: str
            name: str
            email: str

        row_dict = {"id": "123", "name": "John", "email": "john@example.com"}
        user = User.from_row(row_dict)
        assert user.id == "123"
        assert user.name == "John"
        assert user.email == "john@example.com"

    def test_from_row_pydal_row(self) -> None:
        """Test from_row with PyDAL Row object."""

        class User(ElderBaseModel):
            id: str
            name: str

        # Create a real object that looks like PyDAL Row
        class PyDALRow:
            def as_dict(self) -> dict:
                return {"id": "123", "name": "John"}

        mock_row = PyDALRow()
        user = User.from_row(mock_row)
        assert user.id == "123"
        assert user.name == "John"

    def test_from_row_sqlalchemy_row(self) -> None:
        """Test from_row with SQLAlchemy Row object."""

        class User(ElderBaseModel):
            id: str
            name: str

        # Mock SQLAlchemy Row with _mapping attribute
        mock_row = MagicMock()
        mock_row._mapping = {"id": "123", "name": "John"}
        user = User.from_row(mock_row)
        assert user.id == "123"
        assert user.name == "John"

    def test_from_row_iterable_row(self) -> None:
        """Test from_row with iterable Row object."""

        class User(ElderBaseModel):
            id: str
            name: str

        # Create a real iterable object
        row_data = [("id", "123"), ("name", "John")]
        user = User.from_row(row_data)
        assert user.id == "123"
        assert user.name == "John"

    def test_from_row_unsupported_type(self) -> None:
        """Test from_row raises TypeError for unsupported row types."""

        class User(ElderBaseModel):
            id: str
            name: str

        with pytest.raises(TypeError, match="Unsupported row type"):
            User.from_row(123)  # type: ignore

    def test_from_row_filters_none_values(self) -> None:
        """Test from_row filters out None values appropriately."""

        class User(ElderBaseModel):
            id: str
            name: str
            email: Optional[str] = None

        row_dict = {"id": "123", "name": "John", "email": None}
        user = User.from_row(row_dict)
        assert user.id == "123"
        assert user.name == "John"
        assert user.email is None

    def test_from_pydal_row_deprecated(self) -> None:
        """Test from_pydal_row shows deprecation warning."""

        class User(ElderBaseModel):
            id: str
            name: str

        class PyDALRow:
            def as_dict(self) -> dict:
                return {"id": "123", "name": "John"}

        mock_row = PyDALRow()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            user = User.from_pydal_row(mock_row)
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "from_pydal_row() is deprecated" in str(w[0].message)
            assert user.id == "123"

    def test_type_coercion(self) -> None:
        """Test type coercion for common conversions."""

        class Data(ElderBaseModel):
            count: int
            active: bool
            score: float

        data = Data(count="42", active="true", score="3.14")
        assert data.count == 42
        assert data.active is True
        assert data.score == 3.14

    def test_optional_vs_required_fields(self) -> None:
        """Test optional and required field handling."""

        class User(ElderBaseModel):
            id: str
            name: str
            email: Optional[str] = None
            phone: Optional[str] = None

        # Required fields must be provided
        with pytest.raises(ValidationError):
            User(id="123")  # missing 'name'

        # Optional fields are not required
        user = User(id="123", name="John")
        assert user.email is None
        assert user.phone is None

    def test_nested_model_validation(self) -> None:
        """Test nested model validation."""

        class Address(ElderBaseModel):
            street: str
            city: str

        class User(ElderBaseModel):
            id: str
            name: str
            address: Address

        user = User(
            id="123",
            name="John",
            address={"street": "123 Main St", "city": "Springfield"},
        )
        assert user.address.street == "123 Main St"
        assert user.address.city == "Springfield"

        with pytest.raises(ValidationError):
            User(id="123", name="John", address={"street": "123 Main St"})


class TestImmutableModel:
    """Tests for ImmutableModel class."""

    def test_immutable_prevents_modification(self) -> None:
        """Test that ImmutableModel prevents field modification."""

        class UserResponse(ImmutableModel):
            id: str
            name: str

        user = UserResponse(id="123", name="John")
        with pytest.raises(ValidationError):
            user.name = "Jane"

    def test_immutable_rejects_extra_fields(self) -> None:
        """Test that ImmutableModel rejects extra fields."""

        class UserResponse(ImmutableModel):
            id: str
            name: str

        with pytest.raises(ValidationError):
            UserResponse(id="123", name="John", admin=True)

    def test_immutable_serialization(self) -> None:
        """Test ImmutableModel serialization."""

        class UserResponse(ImmutableModel):
            id: str
            name: str
            email: str

        user = UserResponse(id="123", name="John", email="john@example.com")
        assert user.model_dump() == {"id": "123", "name": "John", "email": "john@example.com"}


class TestRequestModel:
    """Tests for RequestModel class."""

    def test_request_model_basic(self) -> None:
        """Test basic RequestModel instantiation."""

        class CreateUserRequest(RequestModel):
            name: str
            email: str

        req = CreateUserRequest(name="John", email="john@example.com")
        assert req.name == "John"
        assert req.email == "john@example.com"

    def test_request_model_rejects_extra_fields(self) -> None:
        """Test that RequestModel rejects unknown fields."""

        class CreateUserRequest(RequestModel):
            name: str
            email: str

        with pytest.raises(ValidationError):
            CreateUserRequest(name="John", email="john@example.com", admin=True)

    def test_request_model_injection_prevention(self) -> None:
        """Test that RequestModel prevents field injection."""

        class UpdateUserRequest(RequestModel):
            name: str
            email: str

        with pytest.raises(ValidationError):
            UpdateUserRequest(name="John", email="john@example.com", is_admin=True)


class TestConfigurableModel:
    """Tests for ConfigurableModel class."""

    def test_configurable_allows_extra_fields(self) -> None:
        """Test that ConfigurableModel allows extra fields."""

        class Config(ConfigurableModel):
            name: str
            version: str

        config = Config(name="app", version="1.0", custom_field="value")
        assert config.name == "app"
        assert config.version == "1.0"

    def test_configurable_extra_fields_access(self) -> None:
        """Test accessing extra fields through __pydantic_extra__."""

        class Config(ConfigurableModel):
            name: str

        config = Config(name="app", custom1="value1", custom2="value2")
        assert config.__pydantic_extra__["custom1"] == "value1"
        assert config.__pydantic_extra__["custom2"] == "value2"

    def test_configurable_to_dict_includes_extra(self) -> None:
        """Test to_dict includes extra fields."""

        class Config(ConfigurableModel):
            name: str
            version: str

        config = Config(name="app", version="1.0", custom_field="value")
        result = config.to_dict()
        assert result == {"name": "app", "version": "1.0", "custom_field": "value"}

    def test_configurable_to_dict_with_exclude_none(self) -> None:
        """Test to_dict with exclude_none and extra fields."""

        class Config(ConfigurableModel):
            name: str
            value: Optional[str] = None

        config = Config(name="app", value=None, extra="data")
        result = config.to_dict(exclude_none=True)
        assert "value" not in result
        assert result["extra"] == "data"


class TestEmailStr:
    """Tests for EmailStr type."""

    def test_valid_email(self) -> None:
        """Test valid email addresses."""

        class User(BaseModel):
            email: EmailStr

        user = User(email="john@example.com")
        assert user.email == "john@example.com"

    def test_invalid_email(self) -> None:
        """Test invalid email addresses."""

        class User(BaseModel):
            email: EmailStr

        with pytest.raises(ValidationError):
            User(email="not-an-email")

    def test_email_normalization(self) -> None:
        """Test email is normalized to lowercase."""

        class User(BaseModel):
            email: EmailStr

        user = User(email="John@Example.COM")
        assert user.email == "john@example.com"


class TestURLStr:
    """Tests for URLStr type."""

    def test_valid_url(self) -> None:
        """Test valid URLs."""

        class Link(BaseModel):
            url: URLStr

        link = Link(url="https://example.com")
        assert link.url == "https://example.com"

    def test_url_with_path(self) -> None:
        """Test URL with path."""

        class Link(BaseModel):
            url: URLStr

        link = Link(url="https://example.com/path/to/page")
        assert link.url == "https://example.com/path/to/page"

    def test_invalid_url(self) -> None:
        """Test invalid URLs."""

        class Link(BaseModel):
            url: URLStr

        with pytest.raises(ValidationError):
            Link(url="not-a-url")

    def test_url_http_scheme(self) -> None:
        """Test HTTP scheme is accepted."""

        class Link(BaseModel):
            url: URLStr

        link = Link(url="http://example.com")
        assert link.url == "http://example.com"


class TestIPAddressStr:
    """Tests for IPAddressStr type."""

    def test_valid_ipv4(self) -> None:
        """Test valid IPv4 addresses."""

        class Server(BaseModel):
            ip: IPAddressStr

        server = Server(ip="192.168.1.1")
        assert server.ip == "192.168.1.1"

    def test_valid_ipv6(self) -> None:
        """Test valid IPv6 addresses."""

        class Server(BaseModel):
            ip: IPAddressStr

        server = Server(ip="::1")
        assert server.ip == "::1"

    def test_invalid_ip(self) -> None:
        """Test invalid IP addresses."""

        class Server(BaseModel):
            ip: IPAddressStr

        with pytest.raises(ValidationError):
            Server(ip="not-an-ip")


class TestIPv4Str:
    """Tests for IPv4Str type."""

    def test_valid_ipv4(self) -> None:
        """Test valid IPv4 addresses."""

        class Server(BaseModel):
            ip: IPv4Str

        server = Server(ip="192.168.1.1")
        assert server.ip == "192.168.1.1"

    def test_ipv6_rejected(self) -> None:
        """Test IPv6 addresses are rejected."""

        class Server(BaseModel):
            ip: IPv4Str

        with pytest.raises(ValidationError):
            Server(ip="::1")


class TestIPv6Str:
    """Tests for IPv6Str type."""

    def test_valid_ipv6(self) -> None:
        """Test valid IPv6 addresses."""

        class Server(BaseModel):
            ip: IPv6Str

        server = Server(ip="::1")
        assert server.ip == "::1"

    def test_ipv4_rejected(self) -> None:
        """Test IPv4 addresses are rejected."""

        class Server(BaseModel):
            ip: IPv6Str

        with pytest.raises(ValidationError):
            Server(ip="192.168.1.1")


class TestHostnameStr:
    """Tests for HostnameStr type."""

    def test_valid_hostname(self) -> None:
        """Test valid hostnames."""

        class Server(BaseModel):
            hostname: HostnameStr

        server = Server(hostname="example.com")
        assert server.hostname == "example.com"

    def test_valid_fqdn(self) -> None:
        """Test valid fully qualified domain names."""

        class Server(BaseModel):
            hostname: HostnameStr

        server = Server(hostname="mail.example.com")
        assert server.hostname == "mail.example.com"

    def test_valid_single_label(self) -> None:
        """Test valid single label hostname."""

        class Server(BaseModel):
            hostname: HostnameStr

        server = Server(hostname="localhost")
        assert server.hostname == "localhost"

    def test_invalid_hostname(self) -> None:
        """Test invalid hostnames."""

        class Server(BaseModel):
            hostname: HostnameStr

        with pytest.raises(ValidationError):
            Server(hostname="--invalid--")


class TestNonEmptyStr:
    """Tests for NonEmptyStr type."""

    def test_valid_non_empty_string(self) -> None:
        """Test valid non-empty strings."""

        class Data(BaseModel):
            value: NonEmptyStr

        data = Data(value="hello")
        assert data.value == "hello"

    def test_empty_string_rejected(self) -> None:
        """Test empty strings are rejected."""

        class Data(BaseModel):
            value: NonEmptyStr

        with pytest.raises(ValidationError):
            Data(value="")

    def test_whitespace_only_rejected(self) -> None:
        """Test whitespace-only strings are rejected."""

        class Data(BaseModel):
            value: NonEmptyStr

        with pytest.raises(ValidationError):
            Data(value="   ")


class TestSlugStr:
    """Tests for SlugStr type."""

    def test_valid_slug(self) -> None:
        """Test valid URL slugs."""

        class Page(BaseModel):
            slug: SlugStr

        page = Page(slug="my-blog-post")
        assert page.slug == "my-blog-post"

    def test_slug_with_numbers(self) -> None:
        """Test slug with numbers."""

        class Page(BaseModel):
            slug: SlugStr

        page = Page(slug="post-123")
        assert page.slug == "post-123"

    def test_invalid_slug_uppercase(self) -> None:
        """Test uppercase characters are rejected."""

        class Page(BaseModel):
            slug: SlugStr

        with pytest.raises(ValidationError):
            Page(slug="MyBlogPost")

    def test_invalid_slug_spaces(self) -> None:
        """Test spaces are rejected."""

        class Page(BaseModel):
            slug: SlugStr

        with pytest.raises(ValidationError):
            Page(slug="my blog post")

    def test_invalid_slug_consecutive_hyphens(self) -> None:
        """Test consecutive hyphens are rejected."""

        class Page(BaseModel):
            slug: SlugStr

        with pytest.raises(ValidationError):
            Page(slug="my--blog--post")


class TestStrongPassword:
    """Tests for StrongPassword type."""

    def test_valid_strong_password(self) -> None:
        """Test valid strong password."""

        class User(BaseModel):
            password: StrongPassword

        user = User(password="SecureP@ss123")
        assert user.password == "SecureP@ss123"

    def test_password_too_short(self) -> None:
        """Test password shorter than minimum."""

        class User(BaseModel):
            password: StrongPassword

        with pytest.raises(ValidationError):
            User(password="Pass@1")

    def test_password_missing_uppercase(self) -> None:
        """Test password missing uppercase letter."""

        class User(BaseModel):
            password: StrongPassword

        with pytest.raises(ValidationError):
            User(password="securepass@123")

    def test_password_missing_lowercase(self) -> None:
        """Test password missing lowercase letter."""

        class User(BaseModel):
            password: StrongPassword

        with pytest.raises(ValidationError):
            User(password="SECUREPASS@123")

    def test_password_missing_digit(self) -> None:
        """Test password missing digit."""

        class User(BaseModel):
            password: StrongPassword

        with pytest.raises(ValidationError):
            User(password="SecurePass@")

    def test_password_missing_special_char(self) -> None:
        """Test password missing special character."""

        class User(BaseModel):
            password: StrongPassword

        with pytest.raises(ValidationError):
            User(password="SecurePass123")

    def test_password_with_space_rejected(self) -> None:
        """Test password with spaces is rejected."""

        class User(BaseModel):
            password: StrongPassword

        with pytest.raises(ValidationError):
            User(password="Secure Pass@123")


class TestModeratePassword:
    """Tests for ModeratePassword type."""

    def test_valid_moderate_password(self) -> None:
        """Test valid moderate password."""

        class User(BaseModel):
            password: ModeratePassword

        user = User(password="SecurePass123")
        assert user.password == "SecurePass123"

    def test_moderate_password_no_special_char_required(self) -> None:
        """Test moderate password doesn't require special characters."""

        class User(BaseModel):
            password: ModeratePassword

        user = User(password="SecurePass123")
        assert user.password == "SecurePass123"

    def test_moderate_password_too_short(self) -> None:
        """Test password shorter than minimum."""

        class User(BaseModel):
            password: ModeratePassword

        with pytest.raises(ValidationError):
            User(password="Pass1")


class TestName255:
    """Tests for Name255 type."""

    def test_valid_name(self) -> None:
        """Test valid names."""

        class User(BaseModel):
            name: Name255

        user = User(name="John Doe")
        assert user.name == "John Doe"

    def test_name_empty_rejected(self) -> None:
        """Test empty names are rejected."""

        class User(BaseModel):
            name: Name255

        with pytest.raises(ValidationError):
            User(name="")

    def test_name_max_255(self) -> None:
        """Test names up to 255 characters."""

        class User(BaseModel):
            name: Name255

        long_name = "A" * 255
        user = User(name=long_name)
        assert user.name == long_name

    def test_name_exceeds_max(self) -> None:
        """Test names exceeding 255 characters."""

        class User(BaseModel):
            name: Name255

        long_name = "A" * 256
        with pytest.raises(ValidationError):
            User(name=long_name)


class TestDescription1000:
    """Tests for Description1000 type."""

    def test_valid_description(self) -> None:
        """Test valid descriptions."""

        class Product(BaseModel):
            description: Description1000

        product = Product(description="A great product")
        assert product.description == "A great product"

    def test_empty_description_allowed(self) -> None:
        """Test empty descriptions are allowed."""

        class Product(BaseModel):
            description: Description1000

        product = Product(description="")
        assert product.description == ""

    def test_description_max_1000(self) -> None:
        """Test descriptions up to 1000 characters."""

        class Product(BaseModel):
            description: Description1000

        long_desc = "A" * 1000
        product = Product(description=long_desc)
        assert product.description == long_desc

    def test_description_exceeds_max(self) -> None:
        """Test descriptions exceeding 1000 characters."""

        class Product(BaseModel):
            description: Description1000

        long_desc = "A" * 1001
        with pytest.raises(ValidationError):
            Product(description=long_desc)


class TestShortText100:
    """Tests for ShortText100 type."""

    def test_valid_text(self) -> None:
        """Test valid short text."""

        class Item(BaseModel):
            title: ShortText100

        item = Item(title="Title")
        assert item.title == "Title"

    def test_empty_text_allowed(self) -> None:
        """Test empty text is allowed."""

        class Item(BaseModel):
            title: ShortText100

        item = Item(title="")
        assert item.title == ""

    def test_text_max_100(self) -> None:
        """Test text up to 100 characters."""

        class Item(BaseModel):
            title: ShortText100

        text = "A" * 100
        item = Item(title=text)
        assert item.title == text

    def test_text_exceeds_max(self) -> None:
        """Test text exceeding 100 characters."""

        class Item(BaseModel):
            title: ShortText100

        text = "A" * 101
        with pytest.raises(ValidationError):
            Item(title=text)


class TestStrongPasswordFactory:
    """Tests for strong_password factory function."""

    def test_custom_strong_password(self) -> None:
        """Test creating custom strong password type."""
        CustomPassword = strong_password(min_length=12, require_special=True)

        class User(BaseModel):
            password: CustomPassword

        user = User(password="VerySecureP@ss123")
        assert user.password == "VerySecureP@ss123"

    def test_custom_password_min_length(self) -> None:
        """Test custom password minimum length."""
        CustomPassword = strong_password(min_length=12)

        class User(BaseModel):
            password: CustomPassword

        with pytest.raises(ValidationError):
            User(password="ShortP@ss1")

    def test_custom_password_no_special_required(self) -> None:
        """Test custom password without special char requirement."""
        CustomPassword = strong_password(
            min_length=8, require_special=False, require_uppercase=True,
            require_lowercase=True, require_digit=True
        )

        class User(BaseModel):
            password: CustomPassword

        user = User(password="NoSpecial123")
        assert user.password == "NoSpecial123"


class TestBoundedStrFactory:
    """Tests for bounded_str factory function."""

    def test_bounded_str_creation(self) -> None:
        """Test creating bounded string type."""
        BoundedString = bounded_str(min_length=5, max_length=10)

        class Data(BaseModel):
            value: BoundedString

        data = Data(value="hello")
        assert data.value == "hello"

    def test_bounded_str_too_short(self) -> None:
        """Test bounded string too short."""
        BoundedString = bounded_str(min_length=5, max_length=10)

        class Data(BaseModel):
            value: BoundedString

        with pytest.raises(ValidationError):
            Data(value="hi")

    def test_bounded_str_too_long(self) -> None:
        """Test bounded string too long."""
        BoundedString = bounded_str(min_length=5, max_length=10)

        class Data(BaseModel):
            value: BoundedString

        with pytest.raises(ValidationError):
            Data(value="this is too long")

    def test_bounded_str_unlimited_max(self) -> None:
        """Test bounded string with unlimited max length."""
        BoundedString = bounded_str(min_length=1, max_length=None)

        class Data(BaseModel):
            value: BoundedString

        long_text = "A" * 1000
        data = Data(value=long_text)
        assert data.value == long_text


class TestValidationErrorResponse:
    """Tests for ValidationErrorResponse class."""

    def test_from_pydantic_error(self) -> None:
        """Test converting Pydantic ValidationError."""

        class User(BaseModel):
            id: int
            name: str

        try:
            User(id="not-an-int", name="")
        except ValidationError as e:
            error_dict, status_code = ValidationErrorResponse.from_pydantic_error(e)
            assert status_code == 400
            assert "validation_errors" in error_dict
            assert error_dict["error"] == "Validation failed"
            assert len(error_dict["validation_errors"]) > 0

    def test_error_response_structure(self) -> None:
        """Test error response structure."""

        class User(BaseModel):
            email: str

        try:
            User(email="invalid-email")
        except ValidationError as e:
            error_dict, _ = ValidationErrorResponse.from_pydantic_error(e)
            for err in error_dict["validation_errors"]:
                assert "field" in err
                assert "message" in err
                assert "type" in err


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_validate_body() -> None:
    """Test validate_body function with Flask context."""
    from flask import Flask

    class UserRequest(RequestModel):
        name: str
        email: str

    app = Flask(__name__)
    with app.test_request_context(json={"name": "John", "email": "john@example.com"}):
        result = validate_body(UserRequest)
        assert result.name == "John"
        assert result.email == "john@example.com"


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_validate_query_params() -> None:
    """Test validate_query_params function with Flask context."""
    from flask import Flask

    class QueryParams(BaseModel):
        page: int
        limit: int

    app = Flask(__name__)
    with app.test_request_context("/?page=1&limit=10"):
        result = validate_query_params(QueryParams)
        assert result.page == 1
        assert result.limit == 10


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_validated_request_decorator_sync() -> None:
    """Test validated_request decorator with sync handler."""
    from flask import Flask

    class CreateUserRequest(RequestModel):
        name: str
        email: str

    @validated_request(body_model=CreateUserRequest)
    def create_user(body: CreateUserRequest):
        return {"status": "created", "user": body.model_dump()}

    app = Flask(__name__)
    with app.test_request_context(json={"name": "John", "email": "john@example.com"}):
        result = create_user()
        assert result["status"] == "created"
        assert result["user"]["name"] == "John"


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
@pytest.mark.asyncio
async def test_validated_request_decorator_async() -> None:
    """Test validated_request decorator with async handler."""
    from flask import Flask

    class CreateUserRequest(RequestModel):
        name: str
        email: str

    @validated_request(body_model=CreateUserRequest)
    async def create_user_async(body: CreateUserRequest):
        return {"status": "created", "user": body.model_dump()}

    app = Flask(__name__)
    with app.test_request_context(json={"name": "John", "email": "john@example.com"}):
        result = await create_user_async()
        assert result["status"] == "created"
        assert result["user"]["name"] == "John"


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_validated_request_validation_error() -> None:
    """Test validated_request decorator handles validation errors."""
    from flask import Flask

    class CreateUserRequest(RequestModel):
        name: str
        email: str

    @validated_request(body_model=CreateUserRequest)
    def create_user(body: CreateUserRequest):
        return {"status": "created"}

    app = Flask(__name__)
    with app.test_request_context(json={"name": "John"}):  # Missing email
        result = create_user()
        assert result[1] == 400
        assert "validation_errors" in result[0]


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_model_response() -> None:
    """Test model_response function."""
    from flask import Flask

    class UserResponse(BaseModel):
        id: str
        name: str
        email: str

    app = Flask(__name__)
    user = UserResponse(id="123", name="John", email="john@example.com")

    with app.app_context():
        response, status_code = model_response(user)
        assert status_code == 200


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_model_response_exclude_none() -> None:
    """Test model_response with exclude_none."""
    from flask import Flask

    class UserResponse(BaseModel):
        id: str
        name: str
        email: Optional[str] = None

    app = Flask(__name__)
    user = UserResponse(id="123", name="John", email=None)

    with app.app_context():
        response, _ = model_response(user, exclude_none=True)
        # Response object from Flask, get_json would need actual response parsing
        assert response is not None


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
def test_model_response_custom_status_code() -> None:
    """Test model_response with custom status code."""
    from flask import Flask

    class UserResponse(BaseModel):
        id: str
        name: str

    app = Flask(__name__)
    user = UserResponse(id="123", name="John")

    with app.app_context():
        response, status_code = model_response(user, status_code=201)
        assert status_code == 201


class TestOpenAPI:
    """Tests for OpenAPI schema generation module."""

    @pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
    def test_generate_openapi_schema(self) -> None:
        """Test generating OpenAPI schema from Pydantic model."""
        from penguin_pydantic.openapi import generate_openapi_schema

        class User(BaseModel):
            id: str
            name: str
            email: str

        schema = generate_openapi_schema(User)
        assert "properties" in schema
        assert "id" in schema["properties"]
        assert "name" in schema["properties"]
        assert "email" in schema["properties"]

    @pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
    def test_generate_openapi_schema_optional_fields(self) -> None:
        """Test OpenAPI schema with optional fields."""
        from penguin_pydantic.openapi import generate_openapi_schema

        class Config(BaseModel):
            name: str
            description: Optional[str] = None

        schema = generate_openapi_schema(Config)
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "description" in schema["properties"]

    @pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask not available")
    def test_pydantic_to_restx_model(self) -> None:
        """Test converting Pydantic model to Flask-RESTX model."""
        try:
            from flask_restx import Api, Resource, fields as restx_fields
            from penguin_pydantic.openapi import pydantic_to_restx_model
            from flask import Flask

            app = Flask(__name__)
            api = Api(app)

            class User(BaseModel):
                id: str
                name: str

            restx_model = pydantic_to_restx_model(api, User)
            assert restx_model is not None
            assert hasattr(restx_model, "name")
            assert restx_model.name == "User"
        except ImportError:
            pytest.skip("Flask-RESTX not available")


class TestAsyncUtils:
    """Tests for async utilities module."""

    @pytest.mark.asyncio
    async def test_run_in_threadpool(self) -> None:
        """Test run_in_threadpool function."""
        from penguin_pydantic.async_utils import run_in_threadpool

        def blocking_function(x: int, y: int) -> int:
            return x + y

        result = await run_in_threadpool(blocking_function, 5, 3)
        assert result == 8

    @pytest.mark.asyncio
    async def test_async_validator_register(self) -> None:
        """Test AsyncValidator registration."""
        from penguin_pydantic.async_utils import AsyncValidator

        validator = AsyncValidator()

        @validator.register("email")
        async def validate_email(db, value, model, **context):
            if "@" not in value:
                raise ValueError("Invalid email")

        assert "email" in validator._validators

    @pytest.mark.asyncio
    async def test_async_validator_validate_model(self) -> None:
        """Test AsyncValidator.validate_model."""
        from penguin_pydantic.async_utils import AsyncValidator

        validator = AsyncValidator()

        @validator.register("email")
        async def validate_email(db, value, model, **context):
            if "@" not in value:
                raise ValueError("Invalid email format")

        class UserModel(BaseModel):
            email: str

        user = UserModel(email="invalid")
        errors = await validator.validate_model(user, None)
        assert len(errors) == 1
        assert errors[0]["field"] == "email"

    @pytest.mark.asyncio
    async def test_validate_foreign_key_exists(self) -> None:
        """Test validate_foreign_key when FK exists."""
        from penguin_pydantic.async_utils import validate_foreign_key

        mock_table = MagicMock()
        mock_table.__getitem__.return_value = {"id": 1}

        await validate_foreign_key(mock_table, 1, "User")

    @pytest.mark.asyncio
    async def test_validate_foreign_key_not_exists(self) -> None:
        """Test validate_foreign_key when FK doesn't exist."""
        from penguin_pydantic.async_utils import validate_foreign_key

        mock_table = MagicMock()
        mock_table.__getitem__.return_value = None

        with pytest.raises(ValueError, match="User with id 1 does not exist"):
            await validate_foreign_key(mock_table, 1, "User")

    @pytest.mark.asyncio
    async def test_validate_unique_field(self) -> None:
        """Test validate_unique_field succeeds when field is unique."""
        from penguin_pydantic.async_utils import validate_unique_field

        # Create a real table-like object
        class MockSelect:
            def first(self):
                return None

        class MockQueryResult:
            def select(self):
                return MockSelect()

        class MockQuery:
            def select(self):
                return MockSelect()

            def __and__(self, other):
                return self

        class MockTable:
            def __getitem__(self, key):
                return MockQuery()

            def __call__(self, query):
                # Return an object with select() method
                return MockQueryResult()

        table = MockTable()
        await validate_unique_field(table, "email", "test@example.com")

    @pytest.mark.asyncio
    async def test_validate_unique_field_exists(self) -> None:
        """Test validate_unique_field when field is not unique."""
        from penguin_pydantic.async_utils import validate_unique_field

        mock_table = MagicMock()
        mock_query = MagicMock()
        mock_table.__getitem__.return_value = mock_query
        mock_query.__and__.return_value = mock_query
        mock_query.select.return_value.first.return_value = {"id": 1}

        with pytest.raises(ValueError, match="email 'test@example.com' already exists"):
            await validate_unique_field(mock_table, "email", "test@example.com")
