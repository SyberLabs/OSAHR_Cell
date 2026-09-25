# Synthetic inventory repair contract

This is an operator-authored contract for a three-component Python application.
All examples use synthetic data. Each component is staged separately as
`service.py`; the assembled application exposes the same files as
`event_decoder.py`, `inventory_reducer.py`, and `availability_api.py`.

## Public interface

```python
# event_decoder.py (service.py when evaluated alone)
def decode_event(raw: str) -> dict[str, object]: ...

# inventory_reducer.py (service.py when evaluated alone)
def apply_event(
    state: dict[str, dict[str, int]], event: dict[str, object]
) -> dict[str, dict[str, int]]: ...

# availability_api.py (service.py when evaluated alone)
def availability(
    state: dict[str, dict[str, int]], sku: str
) -> dict[str, object]: ...
```

`decode_event` accepts one JSON object with exactly four fields: `event_id`
(nonempty string), `sku` (nonempty string), `kind` (`receive`, `reserve`, or
`release`), and `quantity` (positive integer; Boolean is invalid). It returns
those same four fields and values in a dictionary. Malformed JSON, missing or
extra fields, and invalid field values raise `ValueError`.

Inventory state maps each SKU to `{"on_hand": int, "reserved": int}`.
`apply_event` returns a new state without mutating the input. `receive` adds
quantity to `on_hand`. `reserve` adds quantity to `reserved` only when the
current `on_hand - reserved` is sufficient. `release` subtracts quantity from
`reserved` only when the current reserved quantity is sufficient. A new SKU
starts at zero counts; only a `receive` event can create positive stock.
Impossible reservations/releases raise `ValueError` and leave the input state
untouched. Other SKUs remain unchanged.

`availability` returns exactly `{"sku": sku, "on_hand": n, "reserved": r,
"available": n - r}`. An unknown SKU has zero counts. It does not mutate
state. Availability counts are integers, not Booleans or status strings.

The complete application is evaluated by calling `decode_event` on each raw
event, feeding each returned event to `apply_event`, and querying the resulting
state with `availability`. Component acceptance and assembled acceptance both
must pass for the same component revisions.

Public checks under `public/` may be disclosed as debugging feedback. Checks
under `held_out/` are operator-owned final acceptance and must stay outside
builder and controller prompts, generated tests, retrieval records, and memory.
The acceptance filenames intentionally avoid default pytest discovery in the
repository. Run them by explicit file path after staging the appropriate
`service.py` or assembled component modules inside the isolated evaluator.
