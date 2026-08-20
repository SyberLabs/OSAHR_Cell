"""Stable identities and deterministic identity allocation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class EntityId:
    namespace: int
    counter: int

    def __post_init__(self) -> None:
        if self.namespace < 0 or self.counter < 0:
            raise ValueError("EntityId fields must be non-negative")

    def __str__(self) -> str:
        return f"{self.namespace:016x}:{self.counter:016x}"

    @classmethod
    def parse(cls, value: str) -> "EntityId":
        namespace, counter = value.split(":", 1)
        return cls(int(namespace, 16), int(counter, 16))


@dataclass(slots=True)
class IdAllocator:
    namespace: int
    next_counter: int = 0

    def allocate(self) -> EntityId:
        entity_id = EntityId(self.namespace, self.next_counter)
        self.next_counter += 1
        return entity_id

    def reserve_after(self, entity_id: EntityId) -> None:
        if entity_id.namespace == self.namespace:
            self.next_counter = max(self.next_counter, entity_id.counter + 1)
