"""BUDDY Service Registry.

Provides thread-safe service lookup, registration, and lifecycle binding
without unneeded dependency injection complexity.
"""

from __future__ import annotations

import inspect
import threading
from typing import Any, Dict, Optional, Type, TypeVar, Union

from app.core.exceptions import DuplicateServiceError, ServiceNotFoundError

T = TypeVar("T")


class ServiceRegistry:
    """Central registry for core BUDDY runtime services."""

    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def _normalize_key(self, key: Union[str, Type[Any]]) -> str:
        """Derive standard lookup string key from string or Type."""
        if isinstance(key, str):
            normalized = key.strip()
            if not normalized:
                raise ValueError("Service key string cannot be empty")
            return normalized
        if inspect.isclass(key):
            return f"{key.__module__}.{key.__qualname__}"
        raise TypeError(f"Service key must be a string or class type, got {type(key)}")

    def register(
        self,
        key: Union[str, Type[Any]],
        service: Any,
        allow_override: bool = False,
    ) -> None:
        """Register a service under key or class type.

        Raises DuplicateServiceError if already registered and allow_override is False.
        """
        str_key = self._normalize_key(key)
        with self._lock:
            if str_key in self._services and not allow_override:
                raise DuplicateServiceError(str_key)
            self._services[str_key] = service

    def get(
        self,
        key: Union[str, Type[T]],
        default: Optional[Any] = None,
    ) -> T:
        """Retrieve a registered service by string or class type.

        Raises ServiceNotFoundError if not present and no default provided.
        """
        str_key = self._normalize_key(key)
        with self._lock:
            if str_key in self._services:
                return self._services[str_key]
            if default is not None:
                return default
            raise ServiceNotFoundError(str_key)

    def contains(self, key: Union[str, Type[Any]]) -> bool:
        """Return True if service key is registered."""
        try:
            str_key = self._normalize_key(key)
        except (ValueError, TypeError):
            return False
        with self._lock:
            return str_key in self._services

    def remove(self, key: Union[str, Type[Any]]) -> Any:
        """Remove and return a service from the registry.

        Raises ServiceNotFoundError if service was not registered.
        """
        str_key = self._normalize_key(key)
        with self._lock:
            if str_key not in self._services:
                raise ServiceNotFoundError(str_key)
            return self._services.pop(str_key)

    def clear(self) -> None:
        """Clear all registered services."""
        with self._lock:
            self._services.clear()

    def list_services(self) -> list[str]:
        """Return a sorted list of registered service keys."""
        with self._lock:
            return sorted(self._services.keys())
