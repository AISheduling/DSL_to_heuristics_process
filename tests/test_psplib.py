"""
Парсер PSPLIB `.sm`: совпадение с уже обработанным Case 1 и отказ на чужих форматах.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from psplib import PSPLIBFormatError, parse_sm_file, parse_sm_text, split_name

ROOT = Path(__file__).resolve().parents[1]
RAW_J301_1 = ROOT / "data" / "raw" / "1_j301_1.txt"
PSPLIB_DIR = ROOT / "data" / "psplib" / "instances"


def test_j301_1_matches_processed_case1():
    with open(ROOT / "data" / "processed" / "Case1_PSPLIB_j301_1.json", encoding="utf-8") as f:
        expected = json.load(f)
    got = parse_sm_text(RAW_J301_1.read_text(encoding="utf-8"), "j301_1", "PSPLIB J30 Set")
    assert got == expected


@pytest.mark.parametrize("stem, expected", [
    ("j301_1", ("j30", 1, 1)),
    ("j3010_1", ("j30", 10, 1)),
    ("j6048_10", ("j60", 48, 10)),
    ("j12060_10", ("j120", 60, 10)),
    ("Case1", None),
])
def test_split_name(stem, expected):
    assert split_name(stem) == expected


def test_multi_mode_rejected():
    text = RAW_J301_1.read_text(encoding="utf-8").replace(
        "   2        1          3           6  11  15",
        "   2        2          3           6  11  15")
    with pytest.raises(PSPLIBFormatError, match="режимов"):
        parse_sm_text(text, "x")


def test_nonrenewable_rejected():
    text = RAW_J301_1.read_text(encoding="utf-8").replace(
        "  - nonrenewable              :  0   N", "  - nonrenewable              :  2   N")
    with pytest.raises(PSPLIBFormatError, match="невозобновляемые"):
        parse_sm_text(text, "x")


def test_successor_count_mismatch_rejected():
    text = RAW_J301_1.read_text(encoding="utf-8").replace(
        "   2        1          3           6  11  15",
        "   2        1          4           6  11  15")
    with pytest.raises(PSPLIBFormatError, match="преемников"):
        parse_sm_text(text, "x")


@pytest.mark.skipif(not PSPLIB_DIR.exists(), reason="PSPLIB не скачан (data/psplib/SOURCES.md)")
def test_downloaded_j301_1_is_case1():
    got = parse_sm_file(PSPLIB_DIR / "j30" / "j301_1.sm")
    assert got["case_info"]["source"] == "PSPLIB J30 Set"
    assert len(got["jobs"]) == 32
