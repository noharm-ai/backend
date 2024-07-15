from conftest import *
from models.segment import Segment


def seg_getall():
    seg = Segment()
    seg.id = 1
    seg.description = "descript"
    return [seg, seg, seg]


@patch("models.main.User.find", side_effect=user_find)
@patch("models.segment.Segment.findAll", side_effect=seg_getall)
@patch("models.main.dbSession.setSchema", side_effect=setSchema)
def test_get_segments(user, segments, main, client):
    response = client.get("/segments", headers=make_headers(access_token))
    data = json.loads(response.data)

    assert response.status_code == 200
    assert data["status"] == "success"
    assert data["data"][0]["description"] == "descript"
    assert len(data["data"]) == 3
