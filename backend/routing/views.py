from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import HeatmapRequestSerializer, PlaceSearchSerializer, PlanRequestSerializer
from .services.errors import ServiceError
from .services.heatmap import build_heatmap
from .services.places import suggest
from .services.planner import plan_trip


@api_view(['GET'])
def health(request):
    return Response({'status': 'ok'})


@api_view(['POST'])
def plan(request):
    """
    Input:  origin, destination, departure (ISO datetime), load_lb, interval_miles (10/25/50)
    Output: up to 3 routes with checkpoints, risk levels, ETAs, summaries + recommended route.
    """
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        result = plan_trip(**serializer.validated_data)
    except ServiceError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response(result)


@api_view(['POST'])
def heatmap(request):
    """
    Input:  departure, load_lb, paths (route geometries as [[lat, lon], ...])
    Output: hourly wind / rain / snow / risk for a grid of cells around the paths,
            for 0–48 hours after departure.
    """
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        result = build_heatmap(**serializer.validated_data)
    except ServiceError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response(result)


@api_view(['GET'])
def places(request):
    """Autocomplete: GET /api/places/?q=chica -> [{label, lat, lon}, ...]"""
    serializer = PlaceSearchSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    try:
        return Response(suggest(serializer.validated_data['q']))
    except ServiceError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
