"""Unit tests for the JSON body of ``POST /prescriptions``.

The prioritization list takes its filters as a JSON body so a long list of
filters does not overflow the URL. The body is turned into the query string
shape the GET reads, so both methods build the same request.
"""

from werkzeug.datastructures import MultiDict

from routes.prescription import _build_prioritization_request, _json_body_to_args


def test_lists_go_under_brackets_and_scalars_under_the_key():
    """axios writes a list as ``key[]`` and a scalar as ``key``"""
    args = _json_body_to_args(
        {"idSegment": [1, 2], "idDept": [], "pending": True, "agg": 0, "bed": None}
    )

    assert args.getlist("idSegment[]") == ["1", "2"]
    assert args.getlist("idDept[]") == []
    assert args.get("pending") == "true"
    assert args.get("agg") == "0"
    assert "bed" not in args


def test_a_body_that_is_not_an_object_has_no_filters():
    """a list or a scalar body is ignored"""
    assert _json_body_to_args([1, 2]) == MultiDict()


def test_post_and_get_build_the_same_request():
    """the body reads as the query string axios would write"""
    body = {
        "idSegment": [1],
        "idDept": [3, 4],
        "idDrug": [10, 11],
        "pending": False,
        "allDrugs": True,
        "agg": 1,
        "startDate": "2021-03-10",
        "endDate": "all",
        "substances": [5],
        "tags": ["a", "b"],
        "globalScoreMin": 2,
        "diff": None,
        "medicalRecordList": [7],
    }
    query = MultiDict(
        [
            ("idSegment[]", "1"),
            ("idDept[]", "3"),
            ("idDept[]", "4"),
            ("idDrug[]", "10"),
            ("idDrug[]", "11"),
            ("pending", "false"),
            ("allDrugs", "true"),
            ("agg", "1"),
            ("startDate", "2021-03-10"),
            ("endDate", "all"),
            ("substances[]", "5"),
            ("tags[]", "a"),
            ("tags[]", "b"),
            ("globalScoreMin", "2"),
            ("medicalRecordList[]", "7"),
        ]
    )

    from_body = _build_prioritization_request(_json_body_to_args(body))

    assert from_body == _build_prioritization_request(query)
    assert from_body.idSegmentList == [1]
    assert from_body.allDrugs is True
    assert from_body.pending is False
    assert from_body.endDate is None
