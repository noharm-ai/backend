def none2zero(s):
    return float(s) if is_float(s) else 0


def is_float(s):
    try:
        float(s)
        return True
    except:
        return False
