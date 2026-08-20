"""Specified deterministic pseudorandom streams for stochastic replay."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_MASK = (1 << 64) - 1


def _rotl(value: int, shift: int) -> int:
    return ((value << shift) & _MASK) | (value >> (64 - shift))


def _splitmix64(value: int) -> tuple[int, int]:
    value = (value + 0x9E3779B97F4A7C15) & _MASK
    z = value
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
    return value, (z ^ (z >> 31)) & _MASK


def derive_seed(root_seed: int, domain: str) -> int:
    digest = hashlib.blake2b(
        root_seed.to_bytes(16, "little", signed=False) + domain.encode("utf-8"),
        digest_size=8,
        person=b"OSAHR-RNG",
    ).digest()
    return int.from_bytes(digest, "little")


@dataclass(frozen=True, slots=True)
class RandomDraw:
    domain: str
    purpose: str
    raw_uint64: int
    uniform: float
    discarded: bool = False


class Xoshiro256StarStar:
    """xoshiro256** with SplitMix64 seed expansion."""

    def __init__(self, seed: int) -> None:
        state: list[int] = []
        current = seed & _MASK
        for _ in range(4):
            current, word = _splitmix64(current)
            state.append(word)
        if not any(state):
            state[0] = 1
        self._state = state

    def next_u64(self) -> int:
        s0, s1, s2, s3 = self._state
        result = (_rotl((s1 * 5) & _MASK, 7) * 9) & _MASK
        t = (s1 << 17) & _MASK
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = _rotl(s3, 45)
        self._state[:] = [s0 & _MASK, s1 & _MASK, s2 & _MASK, s3 & _MASK]
        return result

    def uniform_open(self) -> tuple[int, float]:
        raw = self.next_u64()
        # Midpoint mapping to the open interval (0, 1).
        uniform = ((raw >> 11) + 0.5) / float(1 << 53)
        return raw, uniform

    def state(self) -> tuple[int, int, int, int]:
        return tuple(self._state)  # type: ignore[return-value]

    def restore(self, state: tuple[int, int, int, int]) -> None:
        if len(state) != 4 or not any(state):
            raise ValueError("Invalid xoshiro state")
        self._state[:] = [word & _MASK for word in state]


class RandomStreams:
    def __init__(self, root_seed: int) -> None:
        if root_seed < 0:
            raise ValueError("root_seed must be non-negative")
        self.root_seed = root_seed
        self._streams: dict[str, Xoshiro256StarStar] = {}

    def stream(self, domain: str) -> Xoshiro256StarStar:
        if domain not in self._streams:
            self._streams[domain] = Xoshiro256StarStar(derive_seed(self.root_seed, domain))
        return self._streams[domain]

    def draw(self, domain: str, purpose: str, *, discarded: bool = False) -> RandomDraw:
        raw, uniform = self.stream(domain).uniform_open()
        return RandomDraw(domain, purpose, raw, uniform, discarded)

    def snapshot(self) -> dict[str, tuple[int, int, int, int]]:
        return {domain: stream.state() for domain, stream in self._streams.items()}

    def restore(self, states: dict[str, tuple[int, int, int, int]]) -> None:
        self._streams = {}
        for domain, state in states.items():
            stream = self.stream(domain)
            stream.restore(state)
