from __future__ import annotations

from osahr_cell.twin import experiment_schema
from osahr_cell.twin import _g6


def test_concept_id_lives_on_experiment_schema_not_6g():
    g6 = _g6()
    assert "concept_id" not in g6.build_schema().vertex_types["Task"].attributes
    assert "concept_id" in experiment_schema().vertex_types["Task"].attributes
