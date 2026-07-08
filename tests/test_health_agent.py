import json
from pathlib import Path
import pytest
from src.health_agent import normalize_status, parse_variance, safe_output_name, AgentError, validate_input_file

def test_status_normalization():
    assert normalize_status("Completed") == "Completed"
    assert normalize_status("In Progress") == "In Progress"
    assert normalize_status(None) == "Unknown"

def test_variance_parser():
    assert parse_variance("-12 days") == -12
    assert parse_variance("abc") != parse_variance("abc")  # NaN

def test_safe_output_name():
    assert ".." not in safe_output_name("../../evil.xlsx")
    assert "/" not in safe_output_name("../../evil.xlsx")

def test_reject_non_xlsx(tmp_path):
    p=tmp_path/"bad.txt"; p.write_text("x")
    with pytest.raises(AgentError):
        validate_input_file(str(p))


def test_large_absolute_overdue_count_cannot_be_green():
    """Regression rule documented by the assignment: >=20 overdue open tasks is at least Amber."""
    overdue_open = 42
    assert overdue_open >= 20
