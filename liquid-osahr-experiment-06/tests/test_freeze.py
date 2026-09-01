from __future__ import annotations

from osahr_cell.freeze import freeze_payload, grammar_checksum, vault_checksum
from osahr_cell.protocol import CONFIRMATORY_SEED, HORIZON


def test_confirmatory_seed_declared():
    assert CONFIRMATORY_SEED == 260826
    assert HORIZON == 60.0


def test_freeze_payload_checksums_vault_and_anlf_versions():
    payload = freeze_payload()
    assert payload["confirmatory_seed_declared"] == CONFIRMATORY_SEED
    assert payload["llm_in_confirmatory"] is False
    assert payload["selects_alpha"] is False
    assert payload["vault_sha256"] == vault_checksum()
    assert payload["grammar_sha256"] == grammar_checksum()
    assert payload["anlf_load_version"].startswith("anlf.load")
    assert payload["anlf_outage_version"].startswith("anlf.outage")
    assert payload["horizon"] == 60.0
