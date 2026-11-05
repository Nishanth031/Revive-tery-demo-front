from __future__ import annotations

import pytest

from revive_ml.contract import Bundle, load_bundle
from revive_ml.convert import convert_demo
from revive_ml.synth import make_clean_bundle


@pytest.fixture(scope="session")
def demo_bundle(tmp_path_factory: pytest.TempPathFactory) -> Bundle:
    out = tmp_path_factory.mktemp("demo") / "bundle"
    return load_bundle(convert_demo(out=out))


@pytest.fixture()
def clean_bundle() -> Bundle:
    return make_clean_bundle(seed=0)
