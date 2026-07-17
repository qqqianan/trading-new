from fastapi.testclient import TestClient

from ashare_lab.main import create_app


def test_health_endpoint_reports_service_ready() -> None:
    # Given: the full ASGI application.
    client = TestClient(create_app())

    # When: readiness is requested.
    response = client.get("/api/v1/health")

    # Then: the service reports a typed success payload.
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data_source": "demo"}


def test_backtest_endpoint_returns_metrics_curve_and_trades() -> None:
    # Given: a valid moving-average request.
    client = TestClient(create_app())
    payload = {
        "symbol": "600519.SH",
        "strategy": "moving_average_cross",
        "initial_cash": 1_000_000,
        "short_window": 10,
        "long_window": 30,
        "allocation": 0.95,
    }

    # When: the strategy is run through the real HTTP boundary.
    response = client.post("/api/v1/backtests", json=payload)

    # Then: an inspectable research result is returned.
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "600519.SH"
    assert len(body["equity_curve"]) > 200
    assert "max_drawdown" in body["metrics"]
    assert isinstance(body["trades"], list)
    assert body["data_quality"]["point_in_time"] is True
    assert body["methodology"]["signal_timing"] == "close_to_next_open"
    assert body["risk_limits"]["max_drawdown"] == 0.2
    assert isinstance(body["risk_events"], list)
