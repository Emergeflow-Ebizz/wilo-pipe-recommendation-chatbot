# (display_name, json_new filename, decimal_head_matching)
# decimal_head_matching=True means heads in this sheet are matched to one
# decimal place (e.g. target 7.2 -> 7.5) instead of the whole-number
# truncate/round-up used by every other sheet. Only PB.json has decimal head
# points among these five; the rest use whole-number heads exclusively.
SHEET_SEQUENCE = [
    ("PB", "PB.json", True),
    ("PW", "PW.json", False),
    ("HWJ-FWJ", "HWJ-FWJ.json", False),
    ("FMHIL", "FMHIL.json", False),
    ("HMHIL", "HMHIL.json", False),
]
