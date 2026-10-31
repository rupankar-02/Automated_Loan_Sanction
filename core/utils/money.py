"""Indian-style money formatting: 602150 -> ₹6,02,150."""


def group_indian(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + out


def inr(n: float | int | None) -> str:
    return "-" if n is None else "₹" + group_indian(round(n))
