"""Deterministic dynamic weighted indices used by stochastic schedulers.

:class:`WeightedIndex` is a deterministic order-statistics treap whose nodes
maintain subtree activity. It supports insertion, deletion, weight updates,
total activity, and inverse-CDF selection in expected O(log n) without a
global rebuild when graph-rewrite occurrences appear or disappear.

The treap priority is derived from a stable digest of the key representation,
so tree shape and uniform-to-event mapping are independent of insertion order.

:func:`select_weighted` is the one-shot linear inverse-CDF used when weights
are already a frozen sequence (time-inhomogeneous thinning).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Generic, Iterator, Sequence, TypeVar

K = TypeVar("K")


def select_weighted(items: Sequence[tuple[K, float]], unit_uniform: float) -> K:
    """Inverse-CDF pick from a frozen weighted sequence. Zero weights are ignored."""
    positive = [(key, float(weight)) for key, weight in items if weight > 0.0]
    total = math.fsum(weight for _, weight in positive)
    if total <= 0.0:
        raise ValueError("Cannot select from zero total weight")
    threshold = min(unit_uniform * total, math.nextafter(total, 0.0))
    cumulative = 0.0
    chosen = positive[-1][0]
    for key, weight in positive:
        cumulative += weight
        if threshold < cumulative:
            return key
    return chosen


@dataclass(frozen=True, slots=True)
class WeightedSelection(Generic[K]):
    key: K
    weight: float


@dataclass(slots=True)
class _Node(Generic[K]):
    key: K
    weight: float
    priority: int
    left: "_Node[K] | None" = None
    right: "_Node[K] | None" = None
    subtree_total: float = 0.0
    subtree_size: int = 1

    def __post_init__(self) -> None:
        self.recalculate()

    def recalculate(self) -> None:
        self.subtree_total = (
            (0.0 if self.left is None else self.left.subtree_total)
            + self.weight
            + (0.0 if self.right is None else self.right.subtree_total)
        )
        self.subtree_size = (
            1
            + (0 if self.left is None else self.left.subtree_size)
            + (0 if self.right is None else self.right.subtree_size)
        )


def _priority(key: object) -> int:
    # repr is deterministic for the key types used by the kernel (strings and
    # frozen dataclass keys containing strings). No Python process hash is used.
    digest = hashlib.blake2b(
        repr(key).encode("utf-8"), digest_size=8, person=b"OSAHR-WI"
    ).digest()
    return int.from_bytes(digest, "big")


def _rotate_right(root: _Node[K]) -> _Node[K]:
    child = root.left
    assert child is not None
    root.left = child.right
    child.right = root
    root.recalculate()
    child.recalculate()
    return child


def _rotate_left(root: _Node[K]) -> _Node[K]:
    child = root.right
    assert child is not None
    root.right = child.left
    child.left = root
    root.recalculate()
    child.recalculate()
    return child


class WeightedIndex(Generic[K]):
    """Canonical dynamic weighted set with inverse-CDF selection."""

    def __init__(self) -> None:
        self._root: _Node[K] | None = None
        self._weights: dict[K, float] = {}

    def __len__(self) -> int:
        return len(self._weights)

    def __contains__(self, key: K) -> bool:
        return key in self._weights

    @staticmethod
    def _validate(weight: float) -> float:
        value = float(weight)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("Weights must be finite and nonnegative")
        return value

    def _insert(self, node: _Node[K] | None, key: K, weight: float) -> _Node[K]:
        if node is None:
            return _Node(key, weight, _priority(key))
        if key == node.key:
            node.weight = weight
        elif key < node.key:  # type: ignore[operator]
            node.left = self._insert(node.left, key, weight)
            if node.left.priority < node.priority:
                node = _rotate_right(node)
        else:
            node.right = self._insert(node.right, key, weight)
            if node.right.priority < node.priority:
                node = _rotate_left(node)
        node.recalculate()
        return node

    def set(self, key: K, weight: float) -> None:
        value = self._validate(weight)
        self._weights[key] = value
        self._root = self._insert(self._root, key, value)

    def _merge(self, left: _Node[K] | None, right: _Node[K] | None) -> _Node[K] | None:
        if left is None:
            return right
        if right is None:
            return left
        if left.priority < right.priority:
            left.right = self._merge(left.right, right)
            left.recalculate()
            return left
        right.left = self._merge(left, right.left)
        right.recalculate()
        return right

    def _remove(self, node: _Node[K] | None, key: K) -> _Node[K] | None:
        if node is None:
            return None
        if key == node.key:
            return self._merge(node.left, node.right)
        if key < node.key:  # type: ignore[operator]
            node.left = self._remove(node.left, key)
        else:
            node.right = self._remove(node.right, key)
        node.recalculate()
        return node

    def remove(self, key: K) -> None:
        if key not in self._weights:
            return
        del self._weights[key]
        self._root = self._remove(self._root, key)

    def clear(self) -> None:
        self._weights.clear()
        self._root = None

    def weight(self, key: K) -> float:
        return self._weights[key]

    @property
    def total(self) -> float:
        return 0.0 if self._root is None else self._root.subtree_total

    def _inorder(self, node: _Node[K] | None) -> Iterator[tuple[K, float]]:
        if node is None:
            return
        yield from self._inorder(node.left)
        yield node.key, node.weight
        yield from self._inorder(node.right)

    def items(self) -> tuple[tuple[K, float], ...]:
        return tuple(self._inorder(self._root))

    def select(self, unit_uniform: float) -> WeightedSelection[K]:
        if not (0.0 < unit_uniform < 1.0):
            raise ValueError("unit_uniform must lie in (0, 1)")
        total = self.total
        if total <= 0.0 or self._root is None:
            raise ValueError("Cannot select from zero total weight")
        threshold = min(unit_uniform * total, math.nextafter(total, 0.0))
        node = self._root
        while node is not None:
            left_total = 0.0 if node.left is None else node.left.subtree_total
            if threshold < left_total:
                node = node.left
                continue
            threshold -= left_total
            if threshold < node.weight:
                return WeightedSelection(node.key, node.weight)
            threshold -= node.weight
            node = node.right
        raise RuntimeError("Weighted tree selection invariant violated")
