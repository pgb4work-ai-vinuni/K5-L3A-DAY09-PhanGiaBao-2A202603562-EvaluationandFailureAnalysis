"""Regression test from docs/trace_case.md: seeded_regression C-002@11.

First wrong step = event 3 `model_override {"delay_days": 5}`: the agent replaced the DB fact
(O-202 delay_days = 2) with the ticket's "trễ 5 ngày", which then produced a 20.000đ refund the
label forbids (status denied, refund 0). The same claim@seed on `fixed` keeps the DB fact.
"""
import pytest

pytestmark = pytest.mark.student


def _graded(shape):
    from pydantic_evals.evaluators import EvaluatorContext
    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, "C-002", 11)
    ctx = EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], graders.DbFactKept().evaluate(ctx).value, graders.RefundAmountCorrect().evaluate(ctx).value


def test_lab9_trace_case_seeded_regression_overrides_db_fact():
    trial, db_fact_kept, amount_ok = _graded("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    first_override = kinds.index("model_override")
    assert kinds[first_override - 1] == "investigator"           # DB read was fine just before
    assert db_fact_kept is False and amount_ok is False
    assert trial["snapshot"]["refund_vnd"] == 20000


def test_lab9_trace_case_fixed_keeps_db_fact():
    trial, db_fact_kept, amount_ok = _graded("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert db_fact_kept is True and amount_ok is True
    assert trial["snapshot"]["refund_vnd"] == 0
