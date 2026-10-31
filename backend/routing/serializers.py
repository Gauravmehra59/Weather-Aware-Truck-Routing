from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .services.checkpoints import ALLOWED_INTERVALS_MILES

# Open-Meteo forecasts reach 15 days ahead. Departure + the 48-hour heatmap window
# (which also covers the trip itself) must fit inside that.
MAX_DAYS_AHEAD = 13
# Small grace period so "leave now" still works after the form sits open a while.
PAST_GRACE = timedelta(hours=1)
MAX_LOAD_LB = 200_000
MAX_PATHS = 3
MAX_POINTS_PER_PATH = 5_000


class LatLonField(serializers.ListField):
    def __init__(self, **kwargs):
        super().__init__(child=serializers.FloatField(), **kwargs)

    def to_internal_value(self, data):
        # Checked here rather than with min/max_length: DRF runs length validators only
        # after to_internal_value, and unpacking below needs exactly two values.
        values = super().to_internal_value(data)
        if len(values) != 2:
            raise serializers.ValidationError('Expected [lat, lon].')
        lat, lon = values
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise serializers.ValidationError('Coordinates out of range.')
        return (lat, lon)


class PlanRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    # Set when the user picked a suggestion: route to exactly that place instead of
    # geocoding the text again (which could pick a different "Springfield").
    origin_point = LatLonField(required=False)
    destination_point = LatLonField(required=False)
    # Naive datetimes are read as UTC (settings.TIME_ZONE); the frontend sends an offset.
    departure = serializers.DateTimeField()
    load_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=ALLOWED_INTERVALS_MILES, default=25)

    def validate_departure(self, value):
        now = timezone.now()
        if value < now - PAST_GRACE:
            raise serializers.ValidationError('Departure time is in the past.')
        if value > now + timedelta(days=MAX_DAYS_AHEAD):
            raise serializers.ValidationError(
                f'Weather forecasts only reach {MAX_DAYS_AHEAD} days ahead.'
            )
        return value

    def validate(self, attrs):
        if attrs['origin'].strip().lower() == attrs['destination'].strip().lower():
            raise serializers.ValidationError('Origin and destination must be different.')
        return attrs


class HeatmapRequestSerializer(serializers.Serializer):
    # Same window as a plan: the heatmap covers 48 hours after departure.
    departure = serializers.DateTimeField()
    load_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    paths = serializers.ListField(
        child=serializers.ListField(
            child=LatLonField(), min_length=2, max_length=MAX_POINTS_PER_PATH
        ),
        min_length=1,
        max_length=MAX_PATHS,
    )

    validate_departure = PlanRequestSerializer.validate_departure


class PlaceSearchSerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, trim_whitespace=True)
