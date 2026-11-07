from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.services.crm_forecast import period_bounds, calculate_scenarios
from app.main import app

def test_calendar_period_bounds_month_quarter_year():
    assert period_bounds("month",date(2026,11,7))==(date(2026,11,1),date(2026,11,30))
    assert period_bounds("quarter",date(2026,11,7))==(date(2026,10,1),date(2026,12,31))
    assert period_bounds("year",date(2026,11,7))==(date(2026,1,1),date(2026,12,31))
    with pytest.raises(ValueError):period_bounds("week",date(2026,1,1))

def test_weighted_forecast_respects_stage_probability_and_override():
    leads=[
      SimpleNamespace(stage="qualified",estimated_value=Decimal("1000"),probability_override=None),
      SimpleNamespace(stage="proposal",estimated_value=Decimal("2000"),probability_override=Decimal("80")),
      SimpleNamespace(stage="won",estimated_value=Decimal("500"),probability_override=None),
      SimpleNamespace(stage="lost",estimated_value=Decimal("400"),probability_override=None)]
    result=calculate_scenarios(leads)
    assert result["best_case"]==Decimal("3000.00")
    assert result["expected"]==Decimal("1850.00")
    assert result["worst_case"]==Decimal("925.00")

def test_configured_scenario_multipliers():
    lead=[SimpleNamespace(stage="proposal",estimated_value=Decimal("100"),probability_override=None)]
    result=calculate_scenarios(lead,{"proposal":60},{"best_case":1.2,"expected":1.0,"worst_case":0.25})
    assert result=={"best_case":Decimal("120.00"),"expected":Decimal("60.00"),"worst_case":Decimal("15.00")}

def test_crm_forecast_and_attribution_routes_are_registered():
    paths=app.openapi()["paths"]
    for path in ["/api/v1/crm/forecast/advanced","/api/v1/crm/forecast/settings",
      "/api/v1/crm/forecast/snapshots","/api/v1/crm/forecast/accuracy",
      "/api/v1/crm/targets","/api/v1/crm/campaigns/{campaign_id}/attributions",
      "/api/v1/crm/campaigns/roi","/api/v1/crm/scheduler/health",
      "/api/v1/crm/leads/{lead_id}/forecast-details"]:
        assert path in paths
