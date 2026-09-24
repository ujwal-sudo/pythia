from scripts.research.pypi_metadata import (
    make_record_id,
    normalize_code_for_hash,
    content_hash,
    make_provenance_chain,
    make_quality_metadata,
    pilot_to_quality_metadata,
)


def test_make_record_id():
    id1 = make_record_id("cffi", "1.15.0")
    id2 = make_record_id("cffi", "1.15.0")
    assert id1 == id2
    assert id1 == "pypi:cffi:1.15.0"


def test_normalize_code_for_hash():
    code_crlf = "def foo():\r\n    pass\r\n"
    code_lf = "def foo():\n    pass\n"
    assert normalize_code_for_hash(code_crlf) == normalize_code_for_hash(code_lf)


def test_content_hash():
    code_crlf = "def foo():\r\n    pass\r\n"
    code_lf = "def foo():\n    pass\n"
    assert content_hash(code_crlf) == content_hash(code_lf)


def test_make_provenance_chain():
    chain = make_provenance_chain(
        source="pypi",
        source_url="https://pypi.org/project/cffi/1.15.0/",
        acquisition_date="2026-09-19",
        experiment_id="PYT-DATA-PYPI-003",
    )
    assert chain["source"] == "pypi"
    assert chain["source_url"] == "https://pypi.org/project/cffi/1.15.0/"


def test_make_provenance_chain_with_versions():
    chain = make_provenance_chain(
        source="pypi",
        source_url="https://pypi.org/project/cffi/1.15.0/",
        acquisition_date="2026-09-19",
        experiment_id="PYT-DATA-PYPI-003",
        preprocessing_version="pypi_preprocessing_v1",
        validator_version="scripts.validators.ast_validator",
        dataset_version="PYTHIA-DATA-v0.1",
    )
    assert chain["preprocessing_version"] == "pypi_preprocessing_v1"


def test_make_quality_metadata():
    meta = make_quality_metadata(
        ast_valid=True,
        license_status="CLEAR",
    )
    assert meta["ast_valid"] is True
    assert meta["license_status"] == "CLEAR"


def test_pilot_to_quality_metadata():
    pilot_data = {"ast_valid": 0, "license_status_dist": {"CLEAR": 772}}
    metadata = pilot_to_quality_metadata(pilot_data)
    assert metadata["ast_valid"] is False
