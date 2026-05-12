from unittest.mock import Mock

from src.tools.providers._http import get_with_retry


def test_get_with_retry_success_first_try():
    mock_session = Mock()
    mock_response = Mock(status_code=200)
    mock_session.get.return_value = mock_response

    response = get_with_retry(mock_session, "https://example.com/api")

    assert response.status_code == 200
    assert mock_session.get.call_count == 1


def test_get_with_retry_handles_429_then_success(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    mock_session = Mock()
    mock_session.get.side_effect = [Mock(status_code=429), Mock(status_code=200)]

    response = get_with_retry(mock_session, "https://example.com/api", max_retries=2)

    assert response.status_code == 200
    assert mock_session.get.call_count == 2


def test_get_with_retry_returns_final_429_after_max_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    mock_session = Mock()
    mock_session.get.return_value = Mock(status_code=429)

    response = get_with_retry(mock_session, "https://example.com/api", max_retries=2)

    assert response.status_code == 429
    assert mock_session.get.call_count == 3  # initial + 2 retries


def test_get_with_retry_returns_500_immediately(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    mock_session = Mock()
    mock_session.get.return_value = Mock(status_code=500)

    response = get_with_retry(mock_session, "https://example.com/api", max_retries=2)

    assert response.status_code == 500
    assert mock_session.get.call_count == 1  # no retry on 5xx
