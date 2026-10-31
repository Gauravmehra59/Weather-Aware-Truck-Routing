class ServiceError(Exception):
    """A third-party service (geocoding, routing, weather) couldn't answer the request.

    The message is safe to show to the user.
    """
