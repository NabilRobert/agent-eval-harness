import pytest

from agent_eval.export import SecretLeakError, assert_no_secrets


def test_a_secret_anywhere_in_the_output_blocks_writing() -> None:
    with pytest.raises(SecretLeakError):
        assert_no_secrets(['{"note": "key dbmcp_abcdef123456 here"}'], ["dbmcp_abcdef123456"])


def test_clean_output_passes() -> None:
    assert_no_secrets(['{"rows": [{"count": 1000}]}'], ["dbmcp_abcdef123456"])
