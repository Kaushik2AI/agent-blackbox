"""Fixture integrity and tool-contract drift."""

import re

from agent_harness.fixtures import list_fixtures, load_fixture
from agent_harness.schemas import CONTRACT_PATH, render
from agent_harness.tools import TOOLS


def test_fixtures_are_versioned_and_hashable() -> None:
    for fid in list_fixtures():
        fx = load_fixture(fid)
        assert re.fullmatch(r"\d+\.\d+\.\d+", fx.fixture_version)
        assert len(fx.content_hash) == 64
        assert fx.content_hash == load_fixture(fid).content_hash


def test_fixture_faults_only_target_allowlisted_tools() -> None:
    for fid in list_fixtures():
        assert set(load_fixture(fid).faults) <= set(TOOLS)


def test_committed_contract_matches_code() -> None:
    assert CONTRACT_PATH.read_text() == render(), (
        "packages/contracts/tools.v1.json is stale: run "
        "`python -m agent_harness.schemas --write` and commit the result"
    )
