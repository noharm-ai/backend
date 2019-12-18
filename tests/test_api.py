import pytest
from io import BytesIO
from mobile import app
import warnings
warnings.filterwarnings('ignore')

@pytest.fixture
def client():
    client = app.test_client()
    yield client

def test_get(client):
	response = client.get('/patient-name/1234')
	assert response.status_code == 200