def mm_to_inch(mm: float) -> float:
    return mm / 25.4


def inch_to_mm(inch: float) -> float:
    return inch * 25.4


def kw_to_hp(kw: float) -> float:
    return kw * 1.34102


def hp_to_kw(hp: float) -> float:
    return hp / 1.34102


def m_to_ft(m: float) -> float:
    return m * 3.28084


def ft_to_m(ft: float) -> float:
    return ft / 3.28084


def lpm_to_gpm(lpm: float) -> float:
    return lpm * 0.264172


def gpm_to_lpm(gpm: float) -> float:
    return gpm / 0.264172
