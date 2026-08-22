"""Dynamic Decorator Factory for Python.

Eliminates the traditional 3-tier nested function boilerplate for Python decorators
by providing a single-tier handler interface backed by dynamic execution context objects.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


class DecoratorContext:
    """Dynamic execution context passed to single-tier decorator handlers.

    Attributes:
        name: The name of the decorator.
        func: The target wrapped function.
        args: Positional arguments passed to target function invocation.
        kwargs: Keyword arguments passed to target function invocation.
        dec_args: Positional arguments passed to the decorator configuration.
        dec_kwargs: Keyword arguments passed to the decorator configuration.
        data: Dynamic attribute store for handler metadata or dynamic attributes.
    """

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        dec_args: tuple[Any, ...],
        dec_kwargs: dict[str, Any],
    ) -> None:
        self.name = name
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.dec_args = dec_args
        self.dec_kwargs = dec_kwargs
        self.data: dict[str, Any] = {}

    def proceed(self, *override_args: Any, **override_kwargs: Any) -> Any:
        """Executes the target wrapped function.

        If positional or keyword argument overrides are provided, they take precedence
        over original invocation arguments. Works seamlessly for sync and async targets.
        """
        call_args = override_args if override_args else self.args
        call_kwargs = {**self.kwargs, **override_kwargs} if override_kwargs else dict(self.kwargs)

        return self.func(*call_args, **call_kwargs)

    def __getattr__(self, item: str) -> Any:
        """Allow dynamic attribute access for custom context data."""
        if item in self.data:
            return self.data[item]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{item}'")

    def __setattr__(self, key: str, value: Any) -> None:
        """Allow dynamic attribute assignment."""
        if key in (
            "name",
            "func",
            "args",
            "kwargs",
            "dec_args",
            "dec_kwargs",
            "data",
        ):
            super().__setattr__(key, value)
        else:
            if "data" not in self.__dict__:
                super().__setattr__("data", {})
            self.data[key] = value

    def __getitem__(self, item: str) -> Any:
        return self.data[item]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __contains__(self, item: str) -> bool:
        return item in self.data

    def __repr__(self) -> str:
        return (
            f"<DecoratorContext(name={self.name!r}, func={self.func.__name__!r}, "
            f"dec_kwargs={self.dec_kwargs!r})>"
        )


HandlerType = Callable[[DecoratorContext], Any]


class DynamicDecorator:
    """Dynamic decorator object representing a configurable decorator instance.

    Can be invoked directly:
        @dec
        def foo(): ...

    Or with decorator configuration arguments:
        @dec(retries=3, delay=1.0)
        def foo(): ...
    """

    def __init__(
        self,
        name: str,
        handler: HandlerType,
        default_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.handler = handler
        self.default_kwargs = default_kwargs or {}

    def __call__(self, *dec_args: Any, **dec_kwargs: Any) -> Any:
        # If passed directly a function as first arg without kwargs, e.g. @decorator
        if (
            len(dec_args) == 1
            and callable(dec_args[0])
            and not dec_kwargs
            and not inspect.isclass(dec_args[0])
            and not getattr(dec_args[0], "_is_decorator_handler", False)
        ):
            func = dec_args[0]
            return self._make_wrapper(func, (), self.default_kwargs)

        # Used with configuration arguments: @decorator(...)
        combined_kwargs = {**self.default_kwargs, **dec_kwargs}

        def decorator_builder(func: Callable[..., Any]) -> Callable[..., Any]:
            return self._make_wrapper(func, dec_args, combined_kwargs)

        return decorator_builder

    def _make_wrapper(
        self,
        func: Callable[..., Any],
        dec_args: tuple[Any, ...],
        dec_kwargs: dict[str, Any],
    ) -> Callable[..., Any]:
        handler = self.handler
        dec_name = self.name
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                ctx = DecoratorContext(
                    name=dec_name,
                    func=func,
                    args=args,
                    kwargs=kwargs,
                    dec_args=dec_args,
                    dec_kwargs=dec_kwargs,
                )
                res = handler(ctx)
                if inspect.isawaitable(res):
                    return await res
                return res

            wrapper = async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                ctx = DecoratorContext(
                    name=dec_name,
                    func=func,
                    args=args,
                    kwargs=kwargs,
                    dec_args=dec_args,
                    dec_kwargs=dec_kwargs,
                )
                res = handler(ctx)
                if inspect.isawaitable(res):
                    return asyncio.run(cast(Any, res))
                return res

            wrapper = sync_wrapper

        wrapper.__decorator_name__ = dec_name
        wrapper.__decorator_config__ = {"args": dec_args, "kwargs": dec_kwargs}
        return wrapper


class DecoratorRegistry:
    """Central registry for dynamic decorators."""

    _instance: DecoratorRegistry | None = None

    def __init__(self) -> None:
        self._decorators: dict[str, DynamicDecorator] = {}

    @classmethod
    def get_global_registry(cls) -> DecoratorRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(
        self,
        name: str,
        handler: HandlerType,
        **default_kwargs: Any,
    ) -> DynamicDecorator:
        dec = DynamicDecorator(name=name, handler=handler, default_kwargs=default_kwargs)
        self._decorators[name] = dec
        return dec

    def get(self, name: str) -> DynamicDecorator:
        if name not in self._decorators:
            raise KeyError(f"Decorator {name!r} is not registered in registry.")
        return self._decorators[name]

    def list(self) -> list[str]:
        return list(self._decorators.keys())

    def clear(self) -> None:
        self._decorators.clear()


def create_decorator(
    name: str,
    handler: HandlerType,
    **default_kwargs: Any,
) -> DynamicDecorator:
    """Creates a dynamic decorator from a single handler function without 3-tier boilerplate.

    Args:
        name: Name identifying the decorator.
        handler: A single function taking `DecoratorContext` and returning result.
        **default_kwargs: Default configuration arguments for the decorator.

    Returns:
        DynamicDecorator instance ready to use as `@decorator` or `@decorator(...)`.
    """
    return DynamicDecorator(name=name, handler=handler, default_kwargs=default_kwargs)


def add_decorator(
    name: str,
    handler: HandlerType | None = None,
    *,
    registry: DecoratorRegistry | None = None,
    **default_kwargs: Any,
) -> DynamicDecorator | Callable[[HandlerType], DynamicDecorator]:
    """Adds a named decorator automatically building out the backend dynamic objects.

    Can be used as a function:
        add_decorator("my-cool-decorator", handler=my_handler)

    Or as a decorator on a handler function:
        @add_decorator(name="my-cool-decorator")
        def my_handler(ctx):
            return ctx.proceed()

    Args:
        name: Name of the decorator.
        handler: Optional single handler function.
        registry: Optional DecoratorRegistry instance (defaults to global registry).
        **default_kwargs: Default decorator keyword arguments.

    Returns:
        DynamicDecorator or builder function if used as decorator.
    """
    reg = registry or DecoratorRegistry.get_global_registry()

    if handler is not None:
        return reg.register(name, handler, **default_kwargs)

    def builder(fn: HandlerType) -> DynamicDecorator:
        return reg.register(name, fn, **default_kwargs)

    return builder


def decorator_factory(
    name: str, **default_kwargs: Any
) -> Callable[[HandlerType], DynamicDecorator]:
    """Decorator that converts a single handler function into a dynamic decorator backend.

    Example:
        @decorator_factory(name="my-cool-decorator", default_timeout=5)
        def my_cool_decorator(ctx: DecoratorContext):
            print(f"Running {ctx.func.__name__}")
            return ctx.proceed()
    """

    def decorator(handler: HandlerType) -> DynamicDecorator:
        return create_decorator(name=name, handler=handler, **default_kwargs)

    return decorator
