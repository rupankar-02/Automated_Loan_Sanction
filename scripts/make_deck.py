"""Build the demo deck: python scripts/make_deck.py [output.pptx]  (needs python-pptx, a dev-only dependency)."""
import sys
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "Document_Copilot_Demo.pptx"
APP_URL = "https://automatedloansanctiongit-dso42uxaa5nuomnxtnihhs.streamlit.app/"
REPO_URL = "github.com/rupankar-02/Automated_Loan_Sanction"

# --- palette: deep navy dominates, one cyan accent, green/amber/red only for status -----------------------------------------------
NAVY, CYAN, INK, GREY = "0B1F44", "00A7E1", "1B2A41", "5B6B82"
WHITE, TINT, MIST = "FFFFFF", "EEF4FA", "DCE8F4"
GREEN, AMBER, RED = "12A150", "E69A00", "D64545"
FONT = "Calibri"


def rgb(h):
    return RGBColor.from_string(h)


prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
prs.core_properties.title = "Document Copilot + Offers Assistant"
prs.core_properties.author = "Rupankar Mitra"
LAYOUT = prs.slide_layouts[5]          # "Title Only": every slide keeps a real title placeholder


def bg(slide, color):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(color)


def text(slide, x, y, w, h, paras, size=16, color=INK, bold=False, italic=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, name=None, after=0):
    """paras: str, or list of str / (str, {size,color,bold,italic}) / list-of-runs."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    items = [paras] if isinstance(paras, str) else paras
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(after)
        runs = item if isinstance(item, list) else [item]
        for r in runs:
            t, o = (r, {}) if isinstance(r, str) else r
            run = p.add_run()
            run.text = t
            f = run.font
            f.name, f.size = FONT, Pt(o.get("size", size))
            f.bold, f.italic = o.get("bold", bold), o.get("italic", italic)
            f.color.rgb = rgb(o.get("color", color))
    return box


def shape(slide, kind, x, y, w, h, fill, line=None, radius=None, name=None):
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if radius is not None and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    if name:
        s.name = name
    return s


def card(slide, x, y, w, h, fill=TINT, line=None, name=None):
    return shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill, line, 0.06, name)


def badge(slide, x, y, d, label, fill=CYAN, color=WHITE, size=16):
    c = shape(slide, MSO_SHAPE.OVAL, x, y, d, d, fill)
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.name, r.font.size, r.font.bold = "Segoe UI Symbol" if not label.isalnum() else FONT, Pt(size), True
    r.font.color.rgb = rgb(color)
    return c


def new_slide(title, dark=False, notes=""):
    s = prs.slides.add_slide(LAYOUT)
    bg(s, NAVY if dark else WHITE)
    t = s.shapes.title
    t.left, t.top, t.width, t.height = Inches(0.6), Inches(0.4), Inches(12.1), Inches(0.95)
    t.text_frame.text = title
    t.text_frame.word_wrap = True
    t.text_frame.margin_left = t.text_frame.margin_right = 0
    t.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = t.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    f = p.runs[0].font
    f.name, f.size, f.bold = FONT, Pt(34), True
    f.color.rgb = rgb(WHITE if dark else NAVY)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


# ======================================================================================================================
# 1. Title
s = new_slide("Document Copilot + Offers Assistant", dark=True, notes=(
    "Open with the problem in one line: loan files bounce back because of the documents, and the customer finds out days later. "
    "We fix that at the moment of upload, and then help the customer understand their offers."))
s.shapes.title.top, s.shapes.title.height, s.shapes.title.width = Inches(2.2), Inches(1.5), Inches(7.2)
s.shapes.title.text_frame.paragraphs[0].runs[0].font.size = Pt(46)
text(s, 0.6, 3.85, 6.9, 1.2, "Get your loan documents right before you submit, then understand your offers in plain language.",
     size=20, color=MIST)
text(s, 0.6, 1.5, 7, 0.4, "AI-POWERED FINANCIAL JOURNEYS  |  LENDING", size=14, color=CYAN, bold=True)
text(s, 0.6, 6.5, 7, 0.4, "Live demo with synthetic data  |  Indicative offers, not an approval", size=14, color=MIST)
# illustration: a checklist stack
for i, (label, st, col) in enumerate([("PAN card", "Verified", GREEN), ("Aadhaar (front, back)", "Verified", GREEN),
                                       ("Salary slips (3 months)", "August 2026 is missing", AMBER), ("Bank statement", "Wrong period", RED)]):
    y = 1.6 + i * 1.15
    card(s, 8.1, y, 4.6, 0.95, fill="16305F", name=f"Checklist card {i + 1}")
    badge(s, 8.35, y + 0.2, 0.55, "✓" if col == GREEN else "!", fill=col, size=18)
    text(s, 9.1, y + 0.14, 3.5, 0.35, label, size=17, color=WHITE, bold=True)
    text(s, 9.1, y + 0.5, 3.5, 0.3, st, size=14, color=MIST)

# 2. Problem
s = new_slide("Loan files bounce back because of the documents", notes=(
    "Three everyday failures. Customers usually find out days after submitting. Existing document-AI tools work for the lender after submission; we work for the borrower before it."))
for i, (head, body) in enumerate([
        ("Unreadable photos", "Blurry, dark or cropped pictures of a PAN card or a bank statement."),
        ("Wrong document or wrong month", "An Aadhaar uploaded as a PAN. A statement for April to June when July to September is needed."),
        ("Typos in the details", "One wrong digit in an IFSC or an Aadhaar number sends the file back.")]):
    x = 0.6 + i * 4.1
    card(s, x, 1.8, 3.8, 3.6, name=f"Problem card {i + 1}")
    badge(s, x + 0.35, 2.1, 0.7, str(i + 1), fill=NAVY, size=22)
    text(s, x + 0.35, 3.0, 3.1, 0.85, head, size=22, bold=True, color=NAVY)
    text(s, x + 0.35, 4.05, 3.1, 1.2, body, size=16, color=GREY)
text(s, 0.6, 5.85, 12.1, 0.8, [[("The customer finds out days later. ", {"bold": True, "color": NAVY}),
                                ("Most document-AI products serve the lender after submission. We check before submission, in the borrower's hands.", {})]],
     size=20, color=INK)

# 3. Idea
s = new_slide("Models read. Rules decide.", notes=(
    "This is the principle behind every screen. AI never approves, rejects or fixes a value on its own. Every accept or reject comes from a rule you can read."))
card(s, 0.6, 1.7, 5.9, 4.0, fill=TINT, name="Models card")
text(s, 0.95, 1.95, 5.2, 0.5, "What the AI does", size=24, bold=True, color=NAVY)
text(s, 0.95, 2.65, 5.2, 2.6, ["Reads the fields printed on a document (Sarvam Vision)",
                                "Explains offers in simple words, in English or Hindi (Gemini, Sarvam 105B)",
                                "Never calculates, never approves, never promises"], size=20, color=INK, after=14)
card(s, 6.85, 1.7, 5.9, 4.0, fill=NAVY, name="Rules card")
text(s, 7.2, 1.95, 5.2, 0.5, "What the rules do", size=24, bold=True, color=WHITE)
text(s, 7.2, 2.65, 5.2, 2.6, ["Validate every value: PAN, Aadhaar checksum, IFSC, dates, amounts",
                               "Check months and periods against the policy",
                               "Decide eligibility and compute every number the assistant quotes"], size=20, color=WHITE, after=14)
text(s, 0.6, 6.1, 12.1, 0.7, "The result: nothing reaches the file, or the customer, that a rule has not checked.", size=20, color=NAVY, bold=True)

# 4. Journey
s = new_slide("One journey, from upload to the lender", notes=(
    "Walk the eight steps. Point out that offers come before KYC on purpose: the customer chooses, then verifies identity for that choice."))
steps = [("Consent", "Clear notice of what is processed"), ("Upload", "Photo, scan or PDF, per checklist"),
         ("Instant checks", "Quality, type, rules, in seconds"), ("Fix and confirm", "Re-checked by the same rules"),
         ("See offers", "Ranked, with reasons and what-ifs"), ("Ask the assistant", "Why not Premium? What can I change?"),
         ("Identity check", "Demo-mode KYC"), ("Lender package", "Selected offer and eligibility run")]
for i, (h, b) in enumerate(steps):
    col, row = i % 4, i // 4
    x, y = 0.6 + col * 3.1, 1.75 + row * 2.55
    card(s, x, y, 2.85, 2.2, fill=TINT if i != 4 else NAVY, name=f"Step {i + 1}")
    dark = i == 4
    badge(s, x + 0.25, y + 0.25, 0.55, str(i + 1), fill=CYAN if dark else NAVY, size=18)
    text(s, x + 0.25, y + 0.95, 2.4, 0.45, h, size=19, bold=True, color=WHITE if dark else NAVY)
    text(s, x + 0.25, y + 1.4, 2.4, 0.7, b, size=14, color=MIST if dark else GREY)

# 5. Checks
s = new_slide("What we catch before you submit", notes=(
    "Every message here is real output from the app. Each says what is wrong, which document, and exactly how to fix it. Blurry, dark and low-resolution photos are caught locally, so they cost nothing."))
items = [("Unreadable photo", "“PAN Card - the photo is blurry. Hold your phone steady, tap to focus and retake.”", RED),
         ("Wrong document", "“This looks like an Aadhaar card (front), but we asked for your PAN card.”", RED),
         ("Wrong bank period", "“This statement covers Apr-Jun 2026, but we need Jul-Sep 2026.”", AMBER),
         ("Missing month", "“Salary slip for August 2026 is missing.”", AMBER),
         ("Invalid value", "IFSC with a typo: shown, corrected by the customer, checked again by the same rule.", AMBER),
         ("Three failed tries", "After 3 attempts a field goes to manual review, so nobody is stuck in a loop.", GREEN)]
for i, (h, b, col) in enumerate(items):
    c, r = i % 2, i // 2
    x, y = 0.6 + c * 6.2, 1.65 + r * 1.75
    card(s, x, y, 5.9, 1.55, name=f"Check card {i + 1}")
    badge(s, x + 0.25, y + 0.3, 0.5, "!" if col != GREEN else "✓", fill=col, size=16)
    text(s, x + 1.0, y + 0.2, 4.7, 0.4, h, size=19, bold=True, color=NAVY)
    text(s, x + 1.0, y + 0.65, 4.7, 0.85, b, size=14, color=GREY, italic=h not in ("Invalid value", "Three failed tries"))

# 6. Architecture
s = new_slide("How it works", notes=(
    "Three lanes. The document lane runs mostly on the user's machine and is free: quality checks and an OCR keyword check for the document type. Only the field reading goes to Sarvam. The offers lane is pure Python. The assistant gets one JSON of precomputed facts and its answer is verified before the user sees it."))
lanes = [("1  Documents", [("Quality gate", "Blur, light, resolution, PDF checks. Local, free."), ("Type check", "Local OCR and keywords. No API call."),
                          ("Field reading", "Sarvam Vision (Document AI)."), ("Rules", "PAN, Aadhaar, IFSC, months, periods.")]),
         ("2  Offers engine", [("Five sample offers", "Criteria in YAML, versioned."), ("Eligibility", "Pass, fail or unknown, with exact gaps."),
                               ("What would it take", "Solver verified by re-running."), ("What-if grids", "Precomputed, never interpolated.")]),
         ("3  Assistant", [("One JSON context", "Masked, derived facts only."), ("One model call", "Gemini, then Sarvam 105B if needed."),
                           ("Number check", "Every figure must be in the context."), ("Safe fallback", "Rules-based answer if it fails.")])]
for li, (lane, parts) in enumerate(lanes):
    x = 0.6 + li * 4.15
    card(s, x, 1.6, 3.9, 4.55, fill=TINT, name=f"Lane {li + 1}")
    text(s, x + 0.3, 1.78, 3.4, 0.45, lane, size=21, bold=True, color=NAVY)
    for pi, (h, b) in enumerate(parts):
        y = 2.4 + pi * 0.92
        card(s, x + 0.25, y, 3.4, 0.8, fill=WHITE, name=f"Lane {li + 1} part {pi + 1}")
        text(s, x + 0.4, y + 0.08, 3.1, 0.3, h, size=15, bold=True, color=NAVY)
        text(s, x + 0.4, y + 0.4, 3.1, 0.35, b, size=12, color=GREY)
text(s, 0.6, 6.4, 12.1, 0.5, "Saved to SQLite: PAN encrypted, Aadhaar and account numbers masked, originals deleted on confirm.",
     size=16, color=NAVY, bold=True)

# 7. Offers
s = new_slide("Offers decided by rules, explained with exact numbers", notes=(
    "This is the borderline demo profile: net income 52,400, score 720, 8,000 of existing EMIs, asking 4 lakh for 36 months. Premium is not open, and the assistant can say exactly why. All lenders and rates here are fictional demo assumptions."))
rows = [("Offer", "Status", "Why / numbers"),
        ("Standard Personal Loan", "Eligible, rank 1", "EMI ₹13,667, total cost ₹98,018"),
        ("Flexi Tenure Loan", "Eligible, rank 2", "EMI ₹13,862, total cost ₹1,07,040"),
        ("Premium Salaried Loan", "Not eligible", "Income ₹7,600 short; score 30 points short; Form 16 missing"),
        ("Quick Small-Ticket Loan", "Not eligible", "Tenure above 12 months; amount above \u20b91,00,000"),
        ("Salary-Linked Advance", "Not eligible", "Tenure above 24 months; amount above \u20b93,00,000")]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.65), Inches(7.6), Inches(3.9)).table
for ci, w in enumerate([2.6, 1.7, 3.3]):
    tbl.columns[ci].width = Inches(w)
for ri, row in enumerate(rows):
    tbl.rows[ri].height = Inches(0.6)
    for ci, val in enumerate(row):
        cell = tbl.cell(ri, ci)
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(NAVY if ri == 0 else (TINT if ri % 2 else WHITE))
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.1)
        tf = cell.text_frame
        tf.word_wrap = True
        r = tf.paragraphs[0].add_run()
        r.text = val
        r.font.name, r.font.size = FONT, Pt(13)
        r.font.bold = ri == 0 or ci == 0
        col = WHITE if ri == 0 else (INK if ci != 1 else (GREEN if val.startswith("Eligible") else RED))
        r.font.color.rgb = rgb(col)
        if ci == 1 and ri:
            r.font.bold = True
card(s, 8.6, 1.65, 4.15, 3.9, fill=NAVY, name="Solver card")
text(s, 8.9, 1.85, 3.6, 0.45, "Not just a no", size=22, bold=True, color=WHITE)
text(s, 8.9, 2.5, 3.6, 2.9, ["Every gap is precomputed, so the assistant never subtracts.",
                              "A solver finds the smallest change that works, and proves it by re-running the engine.",
                              "Sliders show status changes instantly, with no AI."], size=15, color=WHITE, after=10)
text(s, 0.6, 5.85, 12.1, 0.5, "All offers, lenders and rates are fictional demo assumptions, kept in YAML. Offers are indicative, never an approval.",
     size=14, color=GREY, italic=True)

# 8. Assistant results
s = new_slide("An assistant that cannot invent a number", notes=(
    "28 test questions against the real models: offer details, why-not, how to improve, what-if, off-grid amounts, glossary, injection attempts and Hindi. "
    "Every number in every final answer was in the context. When the model slipped, the verifier caught it and the app used the fixed-rules answer instead."))
tiles = [("100%", "numbers traceable to the engine"), ("100%", "expected facts present"), ("2.7 s", "median answer time")]
for i, (big, small) in enumerate(tiles):
    x = 0.6 + i * 2.3
    card(s, x, 1.65, 2.1, 1.55, fill=TINT, name=f"Stat {i + 1}")
    text(s, x, 1.75, 2.1, 0.7, big, size=36, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
    text(s, x + 0.15, 2.5, 1.8, 0.6, small, size=12, color=GREY, align=PP_ALIGN.CENTER)
text(s, 0.6, 3.55, 6.7, 0.4, "How every answer is produced", size=19, bold=True, color=NAVY)
for i, (h, b) in enumerate([("Guard", "Blocks injection and requests for identifiers before any model call."),
                            ("One call", "System rules plus the JSON context, re-sent every time."),
                            ("Verify", "Any number or promise not in the context is rejected."),
                            ("Fallback", "A rules-based answer, so the demo never breaks.")]):
    y = 4.1 + i * 0.68
    badge(s, 0.6, y, 0.45, str(i + 1), fill=CYAN, size=14)
    text(s, 1.25, y + 0.02, 6.0, 0.6, [[(h + ": ", {"bold": True, "color": NAVY}), (b, {})]], size=14, color=GREY)
cd = CategoryChartData()
cd.categories = ["Refused on purpose", "Fixed-rules fallback", "Model answer, verified"]
cd.add_series("Questions", (2, 2, 24))
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(7.7), Inches(1.65), Inches(5.05), Inches(4.7), cd)
gf.name = "Answer outcomes chart"
ch = gf.chart
ch.has_title, ch.has_legend = True, False
ch.chart_title.text_frame.text = "28 test questions: how each was answered"
tr = ch.chart_title.text_frame.paragraphs[0].runs[0].font
tr.name, tr.size, tr.bold = FONT, Pt(14), True
tr.color.rgb = rgb(NAVY)
plot = ch.plots[0]
plot.gap_width = 60
plot.has_data_labels = True
dl = plot.data_labels
dl.position, dl.show_value = XL_LABEL_POSITION.OUTSIDE_END, True
dl.font.name, dl.font.size, dl.font.bold = FONT, Pt(14), True
dl.font.color.rgb = rgb(NAVY)
for idx, col in enumerate([GREY, AMBER, CYAN]):
    pt = plot.series[0].points[idx]
    pt.format.fill.solid()
    pt.format.fill.fore_color.rgb = rgb(col)
ch.category_axis.tick_labels.font.name, ch.category_axis.tick_labels.font.size = FONT, Pt(13)
ch.category_axis.tick_labels.font.color.rgb = rgb(INK)
ch.category_axis.format.line.fill.background()
ch.value_axis.visible = False
ch.value_axis.has_major_gridlines = False
ch.value_axis.maximum_scale = 30
text(s, 7.7, 6.45, 5.05, 0.5, "Refused: a prompt-injection attempt and a request for a PAN number.", size=12, color=GREY, italic=True)

# 9. Privacy
s = new_slide("Built to be trusted with sensitive documents", notes=(
    "Privacy is designed in, not added: PAN stored encrypted, Aadhaar and account numbers masked even in the model's raw value, originals deleted on confirm, and a delete button that really deletes. The prototype uses synthetic documents only."))
items = [("Clear consent", "Names the AI services that process documents, before any upload."),
         ("PAN encrypted", "Stored encrypted at rest, masked as ABCDE****F on screen."),
         ("Aadhaar and account masked", "Only the last 4 digits are kept, in raw and normalized values."),
         ("Originals deleted", "Uploaded files are removed the moment you confirm."),
         ("Delete my data", "One button removes files, fields, offers and chat. Only a value-free audit row remains."),
         ("Honest wording", "Offers are indicative, never an approval. Demo uses synthetic documents only.")]
for i, (h, b) in enumerate(items):
    c, r = i % 3, i // 3
    x, y = 0.6 + c * 4.1, 1.7 + r * 2.5
    card(s, x, y, 3.8, 2.25, name=f"Trust card {i + 1}")
    badge(s, x + 0.3, y + 0.28, 0.55, "✓", fill=GREEN, size=18)
    text(s, x + 1.05, y + 0.3, 2.6, 0.55, h, size=17, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, y + 1.05, 3.25, 1.1, b, size=14, color=GREY)

# 10. Demo flow
s = new_slide("What you will see in the live demo", notes=(
    "Start in Demo mode (no uploads) and choose the Borderline profile. Then show the document path if time allows, using the files in the demo_data folder."))
steps = [("Pick the Borderline profile", "Demo mode loads a verified, fictional applicant."),
         ("See ranked offers", "Standard is rank 1. Premium is not open."),
         ("Ask: why not Premium?", "Exact gaps: income ₹7,600 short, score 30 points short."),
         ("Move the sliders, then Apply", "Statuses change instantly. The chat notes the recalculation."),
         ("Try to trick it", "Ask it to ignore its rules, or about an off-grid amount."),
         ("Select an offer", "Identity check, then the lender package with the full eligibility run.")]
for i, (h, b) in enumerate(steps):
    y = 1.6 + i * 0.82
    badge(s, 0.6, y + 0.04, 0.55, str(i + 1), fill=NAVY, size=18)
    text(s, 1.4, y, 6.3, 0.4, h, size=19, bold=True, color=NAVY)
    text(s, 1.4, y + 0.38, 6.3, 0.35, b, size=14, color=GREY)
card(s, 8.1, 1.6, 4.65, 4.9, fill=NAVY, name="Try it card")
text(s, 8.45, 1.85, 4.0, 0.45, "Try it yourself", size=22, bold=True, color=WHITE)
text(s, 8.45, 2.55, 4.0, 0.4, "Live app", size=13, color=CYAN, bold=True)
text(s, 8.45, 2.85, 4.0, 1.0, APP_URL, size=12, color=WHITE)
text(s, 8.45, 4.0, 4.0, 0.4, "Code", size=13, color=CYAN, bold=True)
text(s, 8.45, 4.3, 4.0, 0.5, REPO_URL, size=13, color=WHITE)
text(s, 8.45, 5.1, 4.0, 1.2, "Open Demo mode first. For uploads use the synthetic files in demo_data, never real documents.",
     size=13, color=MIST, italic=True)

# 11. Limits and next
s = new_slide("Honest about what is mocked, clear about what is next", notes=(
    "Say this plainly. Self-declared EMIs and score, mock KYC and fictional offers are demo choices, and each has a named real replacement."))
card(s, 0.6, 1.65, 5.9, 4.85, fill=TINT, name="Mocked card")
text(s, 0.95, 1.9, 5.2, 0.5, "Mocked or assumed in this demo", size=22, bold=True, color=NAVY)
text(s, 0.95, 2.6, 5.2, 3.8, ["Credit score and existing EMIs are self-declared",
                               "KYC is a demo: any 6-digit OTP, no face match",
                               "Offers, lenders and rates are fictional assumptions in YAML",
                               "We check consistency, not forensic authenticity of documents"], size=19, color=INK, after=16)
card(s, 6.85, 1.65, 5.9, 4.85, fill=NAVY, name="Next card")
text(s, 7.2, 1.9, 5.2, 0.5, "Next", size=22, bold=True, color=WHITE)
text(s, 7.2, 2.6, 5.2, 3.8, ["Derive EMIs from bank transactions, bureau score via a licensed partner",
                              "Real eKYC and CKYC through regulated partners",
                              "Cross-document checks and a full co-applicant flow",
                              "Retrieval over terms and conditions when the catalog outgrows one prompt"], size=19, color=WHITE, after=16)

# 12. Close
s = new_slide("Rules decide. Models explain.", dark=True, notes="Close on the principle, then take questions. Remind judges the app is live and Demo mode is the fastest tour.")
s.shapes.title.top, s.shapes.title.height = Inches(2.3), Inches(1.2)
s.shapes.title.text_frame.paragraphs[0].runs[0].font.size = Pt(46)
text(s, 0.6, 3.7, 9, 1.0, "Documents checked before submission. Offers explained with exact numbers. Nothing the assistant says is a number a rule did not produce.",
     size=20, color=MIST)
text(s, 0.6, 5.6, 12, 0.4, APP_URL, size=16, color=CYAN, bold=True)
text(s, 0.6, 6.05, 12, 0.4, REPO_URL, size=16, color=WHITE)

prs.save(OUT)
print("saved", OUT, "slides:", len(prs.slides))
