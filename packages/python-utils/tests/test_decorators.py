"""Unit tests for the dynamic decorator factory module."""

import asyncio

import pytest

from penguintechinc_utils.decorators import (
    DecoratorContext,
    DecoratorRegistry,
    add_decorator,
    create_decorator,
    decorator_factory,
)


@pytest.fixture(autouse=True)
def clear_registry():
    registry = DecoratorRegistry.get_global_registry()
    registry.clear()
    yield
    registry.clear()


def test_create_decorator_basic_sync():
    def log_handler(ctx: DecoratorContext):
        ctx.executed = True
        result = ctx.proceed()
        return f"wrapped_{result}"

    my_dec = create_decorator("my_logger", handler=log_handler)

    @my_dec
    def greet(name: str):
        """Greet a user."""
        return f"Hello, {name}"

    assert greet.__name__ == "greet"
    assert greet.__doc__ == "Greet a user."
    assert greet("Alice") == "wrapped_Hello, Alice"
    assert greet.__decorator_name__ == "my_logger"


def test_decorator_with_arguments():
    def retry_handler(ctx: DecoratorContext):
        retries = ctx.dec_kwargs.get("max_retries", 1)
        attempts = 0
        last_err = None
        for _ in range(retries):
            attempts += 1
            try:
                return ctx.proceed()
            except ValueError as e:
                last_err = e
        return f"failed_after_{attempts}_attempts:{last_err}"

    retry_dec = create_decorator("retry", handler=retry_handler, max_retries=1)

    @retry_dec(max_retries=3)
    def flaky_func(fail_count: list):
        if fail_count[0] > 0:
            fail_count[0] -= 1
            raise ValueError("temporary error")
        return "success"

    counter = [2]
    res = flaky_func(counter)
    assert res == "success"

    counter_fail = [5]
    res_fail = flaky_func(counter_fail)
    assert res_fail.startswith("failed_after_3_attempts")


@pytest.mark.asyncio
async def test_decorator_async_target():
    def async_handler(ctx: DecoratorContext):
        ctx.started = True
        return ctx.proceed()

    my_dec = create_decorator("async_dec", handler=async_handler)

    @my_dec(tag="async_test")
    async def async_greet(name: str):
        await asyncio.sleep(0.01)
        return f"Async Hello, {name}"

    result = await async_greet("Bob")
    assert result == "Async Hello, Bob"


def test_add_decorator_as_function_and_registry():
    def custom_handler(ctx: DecoratorContext):
        prefix = ctx.dec_kwargs.get("prefix", "DEFAULT:")
        return f"{prefix} {ctx.proceed()}"

    dec = add_decorator("custom_prefix", handler=custom_handler, prefix="PRE:")

    @dec
    def get_msg():
        return "world"

    assert get_msg() == "PRE: world"

    registry = DecoratorRegistry.get_global_registry()
    assert "custom_prefix" in registry.list()
    fetched_dec = registry.get("custom_prefix")
    assert fetched_dec.name == "custom_prefix"


def test_add_decorator_as_decorator_builder():
    @add_decorator(name="metric_counter")
    def count_handler(ctx: DecoratorContext):
        label = ctx.dec_kwargs.get("label", "default")
        res = ctx.proceed()
        return {"label": label, "result": res}

    registry = DecoratorRegistry.get_global_registry()
    metric_dec = registry.get("metric_counter")

    @metric_dec(label="login_attempts")
    def do_login():
        return True

    res = do_login()
    assert res == {"label": "login_attempts", "result": True}


def test_decorator_factory():
    @decorator_factory(name="timing")
    def timing_decorator(ctx: DecoratorContext):
        ctx.data["step"] = "start"
        res = ctx.proceed()
        ctx.data["step"] = "done"
        return {"step": ctx.data["step"], "output": res}

    @timing_decorator
    def compute(x, y):
        return x * y

    assert compute(3, 4) == {"step": "done", "output": 12}


def test_decorator_context_argument_override():
    def override_handler(ctx: DecoratorContext):
        # Override positional and keyword arguments
        return ctx.proceed(10, 20, multiplier=3)

    dec = create_decorator("overrider", handler=override_handler)

    @dec
    def calculate(a, b, multiplier=1):
        return (a + b) * multiplier

    # Call with initial arguments 1, 2
    res = calculate(1, 2)
    assert res == (10 + 20) * 3 == 90


def test_decorator_context_dynamic_attributes():
    ctx = DecoratorContext(
        name="test",
        func=lambda: None,
        args=(),
        kwargs={},
        dec_args=(),
        dec_kwargs={},
    )
    ctx.user_id = 42
    ctx["role"] = "admin"

    assert ctx.user_id == 42
    assert ctx["role"] == "admin"
    assert "role" in ctx
    assert ctx.data == {"user_id": 42, "role": "admin"}
    assert repr(ctx).startswith("<DecoratorContext")
