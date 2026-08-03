"""Tests des calculs géométriques (bbox et distance)."""

from restaurant_finder.geocoding.geo_math import bbox_from_point, haversine_distance_meters


def test_bbox_from_point_is_centered_on_point() -> None:
    bbox = bbox_from_point(45.75, 4.85, radius_meters=1000)

    assert bbox.south < 45.75 < bbox.north
    assert bbox.west < 4.85 < bbox.east
    # ~1km de rayon => delta de latitude proche de 1000/111320 degrés.
    assert abs((bbox.north - 45.75) - (1000 / 111_320)) < 1e-6


def test_bbox_from_point_widens_longitude_near_poles() -> None:
    equator_bbox = bbox_from_point(0.0, 0.0, radius_meters=1000)
    high_latitude_bbox = bbox_from_point(60.0, 0.0, radius_meters=1000)

    equator_lon_span = equator_bbox.east - equator_bbox.west
    high_latitude_lon_span = high_latitude_bbox.east - high_latitude_bbox.west

    assert high_latitude_lon_span > equator_lon_span


def test_haversine_distance_zero_for_identical_points() -> None:
    assert haversine_distance_meters(45.75, 4.85, 45.75, 4.85) == 0.0


def test_haversine_distance_matches_known_approximation() -> None:
    # 1 degré de latitude ~= 111.32 km.
    distance = haversine_distance_meters(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < distance < 112_000
