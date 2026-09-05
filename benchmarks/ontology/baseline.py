"""Independent direct SSA: no OSAHR imports, matcher, compiler, or rewrite code."""
from __future__ import annotations

import math
import random


def transitions(snapshot, state):
    result = {}
    for index, route in enumerate(snapshot.routes):
        rate = route.failure if state[index] else route.repair
        if rate:
            target = list(state)
            target[index] = not target[index]
            result[tuple(target)] = rate
    return result


class DirectSSA:
    def __init__(self, snapshot, seed):
        self.snapshot = snapshot
        self.state = list(snapshot.initial)
        self.time = 0.0
        self.random = random.Random(seed)

    def step(self):
        rates = [r.failure if self.state[i] else r.repair for i, r in enumerate(self.snapshot.routes)]
        total = math.fsum(rates)
        if total == 0:
            return None
        self.time += self.random.expovariate(total)
        threshold = self.random.random() * total
        index = max(i for i, rate in enumerate(rates) if rate > 0)
        accumulated = 0.0
        for i, rate in enumerate(rates):
            accumulated += rate
            if threshold < accumulated:
                index = i
                break
        self.state[index] = not self.state[index]
        return (self.time, index, self.state[index])
