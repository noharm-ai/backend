from flask import g


def is_cpoe():
    return g.get("is_cpoe", False)
