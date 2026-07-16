"""A tiny ordered registry keyed by each item's ``.name``. Shared by the field and
analyzer registries so both get the same add / replace / remove / get semantics —
the pluggability contract lives in one place."""

from __future__ import annotations

from typing import Generic, Iterator, TypeVar

T = TypeVar("T")


class OrderedRegistry(Generic[T]):
    """Insertion-ordered, name-keyed, mutable. Independent instances never share
    state, so a fresh factory (default_fields / default_analyzers) is truly fresh."""

    #: attribute on registered items used as the key
    key = "name"

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def _key(self, item: T) -> str:
        return getattr(item, self.key)

    def add(self, item: T, *, replace: bool = False) -> T:
        name = self._key(item)
        if name in self._items and not replace:
            raise ValueError(
                f"{name!r} already registered (pass replace=True to swap)")
        self._items[name] = item
        return item

    def replace(self, item: T) -> T:
        return self.add(item, replace=True)

    def remove(self, name: str) -> None:
        del self._items[name]

    def get(self, name: str) -> T:
        return self._items[name]

    def all(self) -> list[T]:
        return list(self._items.values())

    def names(self) -> list[str]:
        return list(self._items)

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __iter__(self) -> Iterator[T]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
