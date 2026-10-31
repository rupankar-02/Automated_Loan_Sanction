import pytest

from core.quality.image_checks import blur_score
from core.quality.gate import run_quality_checks
from core.requirements import build_checklist
from tests import synth

DOCS = {d.id: d for d in build_checklist("personal", "salaried")}
PAN, BANK = DOCS["pan"], DOCS["bank_statement"]


def codes(result):
    return {i.code for i in result.issues}


def check(img, spec=PAN, name="pan.jpg"):
    return run_quality_checks(name, synth.to_jpeg(img), spec)[0]


def test_clean_card_passes():
    res = check(synth.good_card())
    assert res.passed and not res.issues, res.issues


def test_blur_scores_separate_sharp_from_blurry():
    sharp = blur_score(synth.good_card())
    soft = blur_score(synth.blurry(synth.good_card()))
    print(f"\ncalibration: sharp={sharp:.0f} blurry={soft:.0f}")
    assert sharp > 3 * soft


def test_blurry_is_rejected_with_specific_message():
    res = check(synth.blurry(synth.good_card()))
    assert not res.passed and "BLURRY" in codes(res)
    issue = next(i for i in res.issues if i.code == "BLURRY")
    assert "PAN Card" in issue.message and "hold your phone steady" in issue.fix_hint
    assert issue.metric["blur_score"] < issue.metric["required"]


def test_dark_and_bright():
    assert "TOO_DARK" in codes(check(synth.dark(synth.good_card())))
    assert "TOO_BRIGHT" in codes(check(synth.bright(synth.good_card())))


def test_low_resolution():
    assert "LOW_RES" in codes(check(synth.low_res(synth.good_card())))


def test_cropped_is_a_warning_not_an_error():
    res = check(synth.cropped())
    assert "CROPPED" in codes(res)
    assert next(i for i in res.issues if i.code == "CROPPED").severity == "warning"


def test_bad_format():
    res = run_quality_checks("scan.gif", b"x" * 50_000, PAN)[0]
    assert codes(res) == {"BAD_FORMAT"}


def test_pdf_not_accepted_for_pan_when_only_image_allowed():
    # PAN accepts image+pdf in config; an unsupported extension is still rejected
    assert "BAD_FORMAT" in codes(run_quality_checks("a.heic", b"x" * 50_000, PAN)[0])


def test_too_large():
    res = run_quality_checks("big.jpg", b"0" * (11 * 1024 * 1024), PAN)[0]
    assert codes(res) == {"FILE_TOO_LARGE"}


def test_too_small_and_corrupt():
    assert codes(run_quality_checks("t.jpg", b"x" * 2000, PAN)[0]) == {"FILE_TOO_SMALL"}
    assert codes(run_quality_checks("c.jpg", b"x" * 60_000, PAN)[0]) == {"UNREADABLE"}


def test_digital_pdf_passes_and_is_rendered():
    res, pages = run_quality_checks("stmt.pdf", synth.text_pdf(2), BANK)
    assert res.passed, res.issues
    assert len(pages) == 2


def test_encrypted_pdf():
    res = run_quality_checks("stmt.pdf", synth.text_pdf(1, password="secret"), BANK)[0]
    assert codes(res) == {"PDF_ENCRYPTED"}


def test_pdf_page_cap():
    res = run_quality_checks("stmt.pdf", synth.text_pdf(35), BANK)[0]
    assert codes(res) == {"PDF_TOO_MANY_PAGES"}


def test_white_scanned_page_is_not_flagged_as_washed_out():
    page = synth.text_page(["SALARY SLIP FOR THE MONTH OF SEP-26", "Employee Name: RAHUL SHARMA", "Net Pay: Rs. 72,500.00"] * 3)
    res = run_quality_checks("slip.jpg", synth.to_jpeg(page), DOCS["salary_slip"])[0]
    assert res.passed, res.issues


def test_sparse_scanned_page_is_not_washed_out():
    page = synth.text_page(["SLIP 1"] * 2)             # almost no ink at all
    res = run_quality_checks("slip.jpg", synth.to_jpeg(page), DOCS["salary_slip"])[0]
    assert res.passed, res.issues
