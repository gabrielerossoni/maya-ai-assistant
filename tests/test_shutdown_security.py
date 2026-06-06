from fastapi import HTTPException


def test_shutdown_rejects_missing_credentials(monkeypatch):
    import main

    monkeypatch.setenv("MAYA_DASHBOARD_TOKEN", "known-token")

    try:
        main._authorize_shutdown(pid=None, token=None, header_token=None)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("shutdown without pid/token must be rejected")


def test_shutdown_accepts_matching_pid(monkeypatch):
    import main

    monkeypatch.setattr(main.os, "getpid", lambda: 1234)

    assert main._authorize_shutdown(pid=1234, token=None, header_token=None) is True


def test_shutdown_accepts_dashboard_token(monkeypatch):
    import main

    monkeypatch.setenv("MAYA_DASHBOARD_TOKEN", "known-token")

    assert main._authorize_shutdown(pid=None, token="known-token", header_token=None) is True
    assert main._authorize_shutdown(pid=None, token=None, header_token="known-token") is True
