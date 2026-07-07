from django.db import connection
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.cloudinary import get_media_client


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return Response({"status": "ok"})


class MediaSignatureView(APIView):
    """POST /media/signature/ — short-lived Cloudinary signed-upload params so
    the client can upload directly (chat attachments, avatars). The API secret
    never leaves the server; the client POSTs the file to `upload_url` with the
    returned fields, then sends us the resulting secure URL.

    Body (optional): { "folder": "chat", "resource_type": "image" }
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        folder = request.data.get("folder") or None
        resource_type = request.data.get("resource_type", "image")
        params = get_media_client().signed_params(
            folder=folder, resource_type=resource_type
        )
        return Response(params)
