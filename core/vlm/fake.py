"""Fake extractor: canned answers for tests and for running the UI without any API.

`detected` and `extracted` may be a single value or a list; a list is consumed one entry per
call (and repeats its last entry), which lets tests script several salary-slip pages.
`by_type` maps a schema doc_type to its canned fields and wins over `extracted`.
"""


def _pick(value, n: int):
    if isinstance(value, list):
        return value[min(n, len(value) - 1)]
    return value


class FakeExtractor:
    def __init__(self, extracted=None, detected="pan", fully_visible: bool = True,
                 legibility: str = "good", fail: bool = False, by_type: dict | None = None,
                 classify_fail: bool = False):
        self.extracted = extracted if extracted is not None else {}
        self.detected = detected
        self.fully_visible = fully_visible
        self.legibility = legibility
        self.fail = fail
        self.by_type = by_type or {}
        self.classify_fail = classify_fail
        self.calls = {"classify": 0, "extract": 0}

    def classify(self, pages):
        n = self.calls["classify"]
        self.calls["classify"] += 1
        if self.classify_fail:
            raise RuntimeError("fake classify failure")
        return {"detected_doc_type": _pick(self.detected, n), "fully_visible": self.fully_visible,
                "legibility": self.legibility}

    def extract(self, fields, pages=None, pdf_bytes=None, doc_type=None, on_wait=None, **_):
        n = self.calls["extract"]
        self.calls["extract"] += 1
        if self.fail:
            raise RuntimeError("fake extraction failure")
        data = self.by_type.get(doc_type, _pick(self.extracted, n))
        return {f["key"]: (data or {}).get(f["key"]) for f in fields}
