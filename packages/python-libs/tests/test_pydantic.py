"""Tests for penguin_libs.pydantic module."""

import asyncio
import json
import warnings
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from pydantic import BaseModel, ValidationError

from penguin_libs.pydantic.async_utils import (
    AsyncValidator,
    run_in_threadpool,
    validate_foreign_key,
    validate_unique_field,
)
from penguin_libs.pydantic.base import (
    ConfigurableModel,
    ElderBaseModel,
    ImmutableModel,
    RequestModel,
)
from penguin_libs.pydantic.flask_integration import (
    ValidationErrorResponse,
    model_response,
    validate_body,
    validate_query_params,
    validated_request,
)
from penguin_libs.pydantic.types import (
    Description1000,
    EmailStr,
    HostnameStr,
    IPAddressStr,
    IPv4Str,
    IPv6Str,
    ModeratePassword,
    Name255,
    NonEmptyStr,
    ShortText100,
    SlugStr,
    StrongPassword,
    URLStr,
    bounded_str,
    strong_password,
)

# ──────────────────────── base.py ────────────────────────


class SampleModel(ElderBaseModel):
    name: str
    age: int
    email: str | None = None


class TestElderBaseModel:
    def test_basic_creation(self):
        m = SampleModel(name="Alice", age=30)
        assert m.name == "Alice"
        assert m.age == 30

    def test_to_dict(self):
        m = SampleModel(name="Bob", age=25, email="bob@x.com")
        d = m.to_dict()
        assert d == {"name": "Bob", "age": 25, "email": "bob@x.com"}

    def test_to_dict_exclude_none(self):
        m = SampleModel(name="Bob", age=25)
        d = m.to_dict(exclude_none=True)
        assert "email" not in d

    def test_to_dict_exclude_unset(self):
        m = SampleModel(name="Bob", age=25)
        d = m.to_dict(exclude_unset=True)
        assert "email" not in d

    def test_from_row_dict(self):
        m = SampleModel.from_row({"name": "Alice", "age": 30})
        assert m.name == "Alice"

    def test_from_row_sqlalchemy_mapping(self):
        row = MagicMock()
        row._mapping = {"name": "Alice", "age": 30}
        del row.as_dict
        m = SampleModel.from_row(row)
        assert m.name == "Alice"

    def test_from_row_as_dict(self):
        row = MagicMock()
        del row._mapping
        row.as_dict.return_value = {"name": "Bob", "age": 25}
        m = SampleModel.from_row(row)
        assert m.name == "Bob"

    def test_from_row_iterable(self):
        class IterableRow:
            def __iter__(self):
                return iter([("name", "Carol"), ("age", 40)])

        m = SampleModel.from_row(IterableRow())
        assert m.name == "Carol"

    def test_from_row_unsupported_type(self):
        class BadRow:
            pass

        with pytest.raises(TypeError, match="Unsupported row type"):
            SampleModel.from_row(BadRow())

    def test_from_row_filters_none_for_non_fields(self):
        m = SampleModel.from_row({"name": "Alice", "age": 30, "email": None, "extra_field": None})
        assert m.name == "Alice"

    def test_from_pydal_row_deprecated(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            m = SampleModel.from_pydal_row({"name": "Old", "age": 50})
            assert len(w) == 1
            assert "deprecated" in str(w[0].message).lower()
            assert m.name == "Old"

    def test_validate_assignment(self):
        m = SampleModel(name="Alice", age=30)
        m.name = "Bob"
        assert m.name == "Bob"

    def test_from_attributes(self):
        class Obj:
            name = "ORM"
            age = 99
            email = None

        m = SampleModel.model_validate(Obj(), from_attributes=True)
        assert m.name == "ORM"

    def test_type_coercion(self):
        m = SampleModel(name="Test", age="25")
        assert m.age == 25


class TestImmutableModel:
    def test_frozen(self):
        class Resp(ImmutableModel):
            id: int
            name: str

        r = Resp(id=1, name="Alice")
        with pytest.raises(ValidationError):
            r.name = "Bob"

    def test_extra_forbidden(self):
        class Resp(ImmutableModel):
            id: int

        with pytest.raises(ValidationError):
            Resp(id=1, extra_field="nope")


class TestRequestModel:
    def test_extra_forbidden(self):
        class Req(RequestModel):
            name: str

        with pytest.raises(ValidationError):
            Req(name="Alice", admin=True)

    def test_valid(self):
        class Req(RequestModel):
            name: str

        r = Req(name="Alice")
        assert r.name == "Alice"


class TestConfigurableModel:
    def test_extra_allowed(self):
        class Cfg(ConfigurableModel):
            name: str

        c = Cfg(name="app", custom_field="value")
        assert c.model_extra.get("custom_field") == "value"

    def test_to_dict_includes_extra(self):
        class Cfg(ConfigurableModel):
            name: str

        c = Cfg(name="app", extra1="a", extra2="b")
        d = c.to_dict()
        assert d["name"] == "app"
        assert d["extra1"] == "a"

    def test_to_dict_no_extra(self):
        class Cfg(ConfigurableModel):
            name: str

        c = Cfg(name="app")
        d = c.to_dict()
        assert d == {"name": "app"}


# ──────────────────────── types.py ────────────────────────


class TestPydanticTypes:
    def test_email_str_valid(self):
        class M(BaseModel):
            email: EmailStr

        m = M(email="user@example.com")
        assert m.email == "user@example.com"

    def test_email_str_invalid(self):
        class M(BaseModel):
            email: EmailStr

        with pytest.raises(ValidationError):
            M(email="bad")

    def test_url_str_valid(self):
        class M(BaseModel):
            url: URLStr

        m = M(url="https://example.com")
        assert m.url == "https://example.com"

    def test_url_str_invalid(self):
        class M(BaseModel):
            url: URLStr

        with pytest.raises(ValidationError):
            M(url="not-a-url")

    def test_ip_address_str(self):
        class M(BaseModel):
            ip: IPAddressStr

        m = M(ip="192.168.1.1")
        assert m.ip == "192.168.1.1"

    def test_ipv4_str(self):
        class M(BaseModel):
            ip: IPv4Str

        m = M(ip="10.0.0.1")
        assert m.ip == "10.0.0.1"

    def test_ipv4_str_rejects_v6(self):
        class M(BaseModel):
            ip: IPv4Str

        with pytest.raises(ValidationError):
            M(ip="::1")

    def test_ipv6_str(self):
        class M(BaseModel):
            ip: IPv6Str

        m = M(ip="::1")
        assert m.ip == "::1"

    def test_hostname_str(self):
        class M(BaseModel):
            host: HostnameStr

        m = M(host="example.com")
        assert m.host == "example.com"

    def test_non_empty_str(self):
        class M(BaseModel):
            val: NonEmptyStr

        m = M(val="hello")
        assert m.val == "hello"
        with pytest.raises(ValidationError):
            M(val="")

    def test_slug_str(self):
        class M(BaseModel):
            slug: SlugStr

        m = M(slug="my-slug")
        assert m.slug == "my-slug"
        with pytest.raises(ValidationError):
            M(slug="BAD SLUG!")

    def test_strong_password_type(self):
        class M(BaseModel):
            pw: StrongPassword

        m = M(pw="MyP@ssw0rd!")
        assert m.pw == "MyP@ssw0rd!"
        with pytest.raises(ValidationError):
            M(pw="weak")

    def test_moderate_password_type(self):
        class M(BaseModel):
            pw: ModeratePassword

        m = M(pw="Secure1Pass")
        assert m.pw is not None

    def test_name255(self):
        class M(BaseModel):
            name: Name255

        m = M(name="John Doe")
        assert m.name == "John Doe"
        with pytest.raises(ValidationError):
            M(name="")

    def test_description1000(self):
        class M(BaseModel):
            desc: Description1000

        m = M(desc="A description")
        assert m.desc == "A description"

    def test_short_text100(self):
        class M(BaseModel):
            text: ShortText100

        m = M(text="Short")
        assert m.text == "Short"
        with pytest.raises(ValidationError):
            M(text="x" * 101)

    def test_strong_password_factory(self):
        CustomPw = strong_password(min_length=12)

        class M(BaseModel):
            pw: CustomPw

        with pytest.raises(ValidationError):
            M(pw="Short1!")

    def test_bounded_str_factory(self):
        Short = bounded_str(0, 5)

        class M(BaseModel):
            val: Short

        m = M(val="hello")
        assert m.val == "hello"
        with pytest.raises(ValidationError):
            M(val="toolong")


# ──────────────────────── async_utils.py ────────────────────────


class TestRunInThreadpool:
    def test_basic(self):
        def add(a, b):
            return a + b

        result = asyncio.get_event_loop().run_until_complete(run_in_threadpool(add, 2, 3))
        assert result == 5


class TestAsyncValidator:
    def test_register_and_validate(self):
        validator_registry = AsyncValidator()

        @validator_registry.register("email")
        async def validate_email(db, value, model, **ctx):
            if value == "taken@example.com":
                raise ValueError("Email already taken")

        class TestModel(BaseModel):
            email: str
            name: str

        model = TestModel(email="taken@example.com", name="Test")
        errors = asyncio.get_event_loop().run_until_complete(
            validator_registry.validate_model(model, db=None)
        )
        assert len(errors) == 1
        assert errors[0]["field"] == "email"
        assert "already taken" in errors[0]["message"]

    def test_validate_no_errors(self):
        validator_registry = AsyncValidator()

        @validator_registry.register("name")
        async def validate_name(db, value, model, **ctx):
            pass

        class TestModel(BaseModel):
            name: str

        model = TestModel(name="Good")
        errors = asyncio.get_event_loop().run_until_complete(
            validator_registry.validate_model(model, db=None)
        )
        assert len(errors) == 0

    def test_validate_missing_field(self):
        validator_registry = AsyncValidator()

        @validator_registry.register("nonexistent")
        async def validate_nope(db, value, model, **ctx):
            raise ValueError("should not be called")

        class TestModel(BaseModel):
            name: str

        model = TestModel(name="Test")
        errors = asyncio.get_event_loop().run_until_complete(
            validator_registry.validate_model(model, db=None)
        )
        assert len(errors) == 0


class TestValidateForeignKey:
    def test_exists(self):
        table = MagicMock()
        table.__getitem__ = MagicMock(return_value={"id": 1})
        asyncio.get_event_loop().run_until_complete(validate_foreign_key(table, 1, "User"))

    def test_not_exists(self):
        table = MagicMock()
        table.__getitem__ = MagicMock(return_value=None)
        with pytest.raises(ValueError, match="User with id 1"):
            asyncio.get_event_loop().run_until_complete(validate_foreign_key(table, 1, "User"))


class TestValidateUniqueField:
    def _make_table(self, existing=None):
        """Create a mock PyDAL table that returns existing on query."""
        table = MagicMock()
        # table(query) returns a mock with .select().first()
        query_mock = MagicMock()
        query_mock.select.return_value.first.return_value = existing
        table.return_value = query_mock
        return table

    def test_unique(self):
        table = self._make_table(existing=None)
        asyncio.get_event_loop().run_until_complete(
            validate_unique_field(table, "email", "new@example.com")
        )

    def test_duplicate(self):
        table = self._make_table(existing={"id": 1})
        with pytest.raises(ValueError, match="already exists"):
            asyncio.get_event_loop().run_until_complete(
                validate_unique_field(table, "email", "taken@example.com")
            )

    def test_exclude_id(self):
        table = self._make_table(existing=None)
        asyncio.get_event_loop().run_until_complete(
            validate_unique_field(table, "email", "test@example.com", exclude_id=5)
        )


# ──────────────────────── flask_integration.py ────────────────────────


def _create_app():
    """Create a minimal Flask app for testing."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


class TestValidationErrorResponse:
    def test_from_pydantic_error(self):
        class StrictModel(BaseModel):
            name: str
            age: int

        app = _create_app()
        with app.app_context():
            try:
                StrictModel(name=123, age="not-int")
            except ValidationError as e:
                result, status = ValidationErrorResponse.from_pydantic_error(e)
                assert status == 400
                assert result["error"] == "Validation failed"
                assert len(result["validation_errors"]) > 0
                err = result["validation_errors"][0]
                assert "field" in err
                assert "message" in err
                assert "type" in err

    def test_without_app_context(self):
        class StrictModel(BaseModel):
            age: int

        try:
            StrictModel(age="not-int")
        except ValidationError as e:
            # Should not raise even without app context
            result, status = ValidationErrorResponse.from_pydantic_error(e)
            assert status == 400


class TestValidateBody:
    def test_validate_body(self):
        class MyModel(BaseModel):
            name: str

        app = _create_app()
        with app.test_request_context("/test", method="POST", json={"name": "Alice"}):
            m = validate_body(MyModel)
            assert m.name == "Alice"


class TestValidateQueryParams:
    def test_validate_query(self):
        class Params(BaseModel):
            page: int = 1

        app = _create_app()
        with app.test_request_context("/test?page=2"):
            p = validate_query_params(Params)
            assert p.page == 2


class TestValidatedRequest:
    def test_sync_decorator_with_body(self):
        class Body(BaseModel):
            name: str

        app = _create_app()

        @validated_request(body_model=Body)
        def handler(body=None):
            return {"name": body.name}

        with app.test_request_context("/test", method="POST", json={"name": "Test"}):
            result = handler()
            assert result == {"name": "Test"}

    def test_sync_decorator_validation_error(self):
        class Body(RequestModel):
            name: str
            age: int

        app = _create_app()

        @validated_request(body_model=Body)
        def handler(body=None):
            return {"name": body.name}

        with app.test_request_context(
            "/test", method="POST", json={"name": "Test", "age": "not-int"}
        ):
            result = handler()
            assert isinstance(result, tuple)
            assert result[1] == 400

    def test_sync_decorator_with_query(self):
        class Query(BaseModel):
            page: int = 1

        app = _create_app()

        @validated_request(query_model=Query)
        def handler(query=None):
            return {"page": query.page}

        with app.test_request_context("/test?page=3"):
            result = handler()
            assert result == {"page": 3}

    def test_async_decorator(self):
        class Body(BaseModel):
            name: str

        app = _create_app()

        @validated_request(body_model=Body)
        async def handler(body=None):
            return {"name": body.name}

        with app.test_request_context("/test", method="POST", json={"name": "Async"}):
            result = asyncio.get_event_loop().run_until_complete(handler())
            assert result == {"name": "Async"}

    def test_async_decorator_validation_error(self):
        class Body(RequestModel):
            name: str
            age: int

        app = _create_app()

        @validated_request(body_model=Body)
        async def handler(body=None):
            return {"name": body.name}

        with app.test_request_context("/test", method="POST", json={"name": "X", "age": "bad"}):
            result = asyncio.get_event_loop().run_until_complete(handler())
            assert isinstance(result, tuple)
            assert result[1] == 400

    def test_async_decorator_with_query(self):
        class Query(BaseModel):
            page: int = 1

        app = _create_app()

        @validated_request(query_model=Query)
        async def handler(query=None):
            return {"page": query.page}

        with app.test_request_context("/test?page=5"):
            result = asyncio.get_event_loop().run_until_complete(handler())
            assert result == {"page": 5}


class TestModelResponse:
    def test_model_response_with_app_context(self):
        class Resp(BaseModel):
            id: int
            name: str

        app = _create_app()
        r = Resp(id=1, name="Alice")
        with app.test_request_context():
            response, status = model_response(r)
            assert status == 200
            data = response.get_json()
            assert data["name"] == "Alice"

    def test_model_response_no_app_context(self):
        class Resp(BaseModel):
            id: int
            name: str

        r = Resp(id=1, name="Alice")
        # Outside app context, model_response creates a raw Response
        response, status = model_response(r)
        assert status == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["name"] == "Alice"

    def test_model_response_exclude_none(self):
        class Resp(BaseModel):
            id: int
            name: str | None = None

        app = _create_app()
        r = Resp(id=1)
        with app.test_request_context():
            response, status = model_response(r, exclude_none=True)
            data = response.get_json()
            assert "name" not in data

    def test_model_response_custom_status(self):
        class Resp(BaseModel):
            id: int

        app = _create_app()
        r = Resp(id=1)
        with app.test_request_context():
            _, status = model_response(r, status_code=201)
            assert status == 201


# ──────────────────────── openapi.py ────────────────────────


class TestOpenAPI:
    def test_generate_openapi_schema(self):
        from penguin_libs.pydantic.openapi import generate_openapi_schema

        class UserModel(BaseModel):
            name: str
            age: int
            email: str | None = None

        schema = generate_openapi_schema(UserModel)
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]

    def test_pydantic_to_restx_field_basic_types(self):
        try:
            from penguin_libs.pydantic.openapi import pydantic_to_restx_field

            class TestModel(BaseModel):
                name: str
                age: int
                score: float
                active: bool

            for field_name, field_info in TestModel.model_fields.items():
                result = pydantic_to_restx_field(field_info, field_info.annotation)
                assert result is not None
        except ImportError:
            pytest.skip("flask-restx not installed")

    def test_pydantic_to_restx_field_list(self):
        try:
            from flask_restx import fields as restx_fields

            from penguin_libs.pydantic.openapi import pydantic_to_restx_field

            class TestModel(BaseModel):
                tags: list[str]

            field_info = TestModel.model_fields["tags"]
            result = pydantic_to_restx_field(field_info, field_info.annotation)
            assert isinstance(result, restx_fields.List)
        except ImportError:
            pytest.skip("flask-restx not installed")

    def test_pydantic_to_restx_field_dict(self):
        try:
            from flask_restx import fields as restx_fields

            from penguin_libs.pydantic.openapi import pydantic_to_restx_field

            class TestModel(BaseModel):
                meta: dict[str, Any]

            field_info = TestModel.model_fields["meta"]
            result = pydantic_to_restx_field(field_info, field_info.annotation)
            assert isinstance(result, restx_fields.Raw)
        except ImportError:
            pytest.skip("flask-restx not installed")

    def test_pydantic_to_restx_model(self):
        try:
            from flask_restx import Api

            from penguin_libs.pydantic.openapi import pydantic_to_restx_model

            app = Flask(__name__)
            api = Api(app)

            class UserModel(BaseModel):
                name: str
                age: int

            model = pydantic_to_restx_model(api, UserModel)
            assert model is not None

            model2 = pydantic_to_restx_model(api, UserModel, name="CustomUser")
            assert model2 is not None
        except ImportError:
            pytest.skip("flask-restx not installed")


# ──────────────────────── __init__.py ────────────────────────


class TestPydanticModuleExports:
    def test_all_exports(self):
        from penguin_libs.pydantic import __all__

        assert "ElderBaseModel" in __all__
        assert "EmailStr" in __all__
        assert "validated_request" in __all__


class TestSecurityModule:
    def test_security_init_imports(self):
        from penguin_libs.security import __all__

        assert "sanitize_html" in __all__
        assert "generate_csrf_token" in __all__
        assert "hash_password" in __all__
        assert "validate_body" in __all__
        assert "ElderBaseModel" in __all__
