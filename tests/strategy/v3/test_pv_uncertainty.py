from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from minyad.strategy.v3.pv_uncertainty import (
    classify_cloud_cover,
    collect_pv_ratio_samples,
    compute_uncertainty_bands,
    percentile,
)

TZ = ZoneInfo("Europe/Amsterdam")
UTC = timezone.utc


def test_classify_cloud_cover_boundaries():
    assert classify_cloud_cover(0.0) == "clear"
    assert classify_cloud_cover(24.9) == "clear"
    assert classify_cloud_cover(25.0) == "partly"
    assert classify_cloud_cover(74.9) == "partly"
    assert classify_cloud_cover(75.0) == "cloudy"
    assert classify_cloud_cover(100.0) == "cloudy"


def test_percentile_matches_known_values():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 0.0) == 10.0
    assert percentile(values, 100.0) == 50.0
    assert percentile(values, 50.0) == 30.0


def test_percentile_interpolates_between_ranks():
    values = [0.0, 10.0]
    assert percentile(values, 25.0) == 2.5


def test_percentile_empty_is_zero():
    assert percentile([], 10.0) == 0.0


def test_percentile_single_value():
    assert percentile([42.0], 90.0) == 42.0


def test_collect_pv_ratio_samples_classifies_by_cloud_cover():
    ts = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    rows = [(ts, 400.0)]
    ghi_points = [(ts, 100.0)]
    cloud_points = [(ts, 10.0)]  # clear
    factors = [7.0] * 24
    ratios = collect_pv_ratio_samples(rows, ghi_points, cloud_points, factors, TZ)
    # predicted = 100 * 7.0 = 700; actual/predicted = 400/700
    assert ratios["clear"] == [400.0 / 700.0]
    assert ratios["partly"] == []
    assert ratios["cloudy"] == []


def test_collect_pv_ratio_samples_excludes_below_ghi_threshold():
    ts = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
    rows = [(ts, 20.0)]
    ghi_points = [(ts, 30.0)]  # below the 50 W/m2 default threshold
    cloud_points = [(ts, 10.0)]
    factors = [7.0] * 24
    ratios = collect_pv_ratio_samples(rows, ghi_points, cloud_points, factors, TZ)
    assert ratios == {"clear": [], "partly": [], "cloudy": []}


def test_compute_uncertainty_bands_omits_class_below_min_samples():
    ratios_by_class = {"clear": [1.0] * 5, "partly": [], "cloudy": []}
    bands = compute_uncertainty_bands(ratios_by_class, min_samples=10)
    assert bands == {}


def test_compute_uncertainty_bands_includes_class_with_enough_samples():
    ratios_by_class = {"clear": [0.8, 0.9, 1.0, 1.1, 1.2], "partly": [], "cloudy": []}
    bands = compute_uncertainty_bands(ratios_by_class, min_samples=5)
    assert "clear" in bands
    assert bands["clear"]["p10_multiplier"] < bands["clear"]["p90_multiplier"]
    assert bands["clear"]["sample_count"] == 5
    assert "partly" not in bands
    assert "cloudy" not in bands
