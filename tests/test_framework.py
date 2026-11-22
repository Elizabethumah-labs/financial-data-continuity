import numpy as np
import pytest

from fdcf.adapters import PATHS
from fdcf.hypercare import exit_criteria_met, signals, xmr_limits
from fdcf.ledger import LedgerSpec, generate_ledger
from fdcf.migrate import BENIGN, DEFECTS, migrate
from fdcf.reconcile import baseline_checks, go_live_gate, load_registry, reconcile

REG = load_registry()


@pytest.fixture(scope="module")
def legacy():
    return generate_ledger(LedgerSpec(seed=3, docs_per_period=60))


def test_every_document_balances(legacy):
    assert legacy.groupby("doc_id")["amount"].sum().abs().max() < 0.005


@pytest.mark.parametrize("path", list(PATHS))
@pytest.mark.parametrize("side", ["source", "target"])
def test_adapters_round_trip(legacy, path, side):
    to, frm = PATHS[path][side]
    back = frm(to(legacy))
    assert len(back) == len(legacy)
    assert back["amount"].sum() == pytest.approx(legacy["amount"].sum(), abs=0.01)
    assert sorted(back["account"]) == sorted(legacy["account"])


@pytest.mark.parametrize("path", list(PATHS))
@pytest.mark.parametrize("scenario", BENIGN)
def test_benign_changes_pass_the_gate(legacy, path, scenario):
    to, frm = PATHS[path]["target"]
    m = migrate(legacy, scenario, seed=3)
    assert go_live_gate(reconcile(legacy, frm(to(m.target)), REG, m.exclusions)) == "GO"


@pytest.mark.parametrize("path", list(PATHS))
@pytest.mark.parametrize("scenario", DEFECTS)
def test_seeded_defects_fail_the_gate(legacy, path, scenario):
    to, frm = PATHS[path]["target"]
    m = migrate(legacy, scenario, seed=3)
    assert go_live_gate(reconcile(legacy, frm(to(m.target)), REG, m.exclusions)) == "NO-GO"


def test_baseline_misses_sign_flip(legacy):
    m = migrate(legacy, "sign_flip_document", seed=3)
    assert not any(baseline_checks(legacy, m.target, m.exclusions).values())


def test_control_chart_flags_large_shift():
    base = np.array([40, 42, 38, 41, 39, 40, 43, 37, 40, 41, 39, 40], dtype=float)
    lim = xmr_limits(base)
    assert signals(base, lim) == []
    assert signals(np.array([60.0, 61, 62]), lim)
    assert not exit_criteria_met([60, 61, 62], lim, [True, True, True])
    assert exit_criteria_met([40, 41, 39], lim, [True, True, True])
