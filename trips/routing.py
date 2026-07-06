from django.urls import re_path

from trips.consumers import TripConsumer

websocket_urlpatterns = [
    re_path(r"^ws/trips/(?P<trip_id>[0-9a-f-]+)/$", TripConsumer.as_asgi()),
]
