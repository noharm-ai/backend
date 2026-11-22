def none2zero(s):
    return float(s) if is_float(s) else 0


def is_float(s):
    try:
        float(s)
        return True
    except Exception:
        return False


def round_significant(value: float, digits: int = 7) -> float:
    """value with `digits` significant digits (7: what a float4 holds), to drop
    the float noise of a product or a sum before it is compared or shown:
    0.1 * 3 is 0.30000000000000004, rounded it is 0.3"""
    return float(f"{value:.{digits}g}")
