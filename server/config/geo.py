from math import asin, cos, radians, sin, sqrt


def distance_m(latitude_one, longitude_one, latitude_two, longitude_two) -> float:
    first_latitude = radians(float(latitude_one))
    second_latitude = radians(float(latitude_two))
    latitude_delta = second_latitude - first_latitude
    longitude_delta = radians(float(longitude_two) - float(longitude_one))
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(first_latitude) * cos(second_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 6_371_000 * 2 * asin(sqrt(haversine))
