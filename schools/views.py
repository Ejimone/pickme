from rest_framework import exceptions, filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from schools.models import School
from schools.serializers import (
    SchoolCalendarExceptionSerializer,
    SchoolSerializer,
)


class SchoolViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Shared reference data: any authenticated user can list, add, edit."""

    queryset = School.objects.order_by("name")
    serializer_class = SchoolSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "address"]

    @action(
        detail=True, methods=["get", "post"], url_path="calendar-exceptions"
    )
    def calendar_exceptions(self, request, pk=None):
        school = self.get_object()
        if request.method == "POST":
            serializer = SchoolCalendarExceptionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            if school.calendar_exceptions.filter(
                date=serializer.validated_data["date"]
            ).exists():
                raise exceptions.ValidationError(
                    {"date": ["An exception for this date already exists."]}
                )
            serializer.save(school=school)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        qs = school.calendar_exceptions.order_by("date")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        page = self.paginate_queryset(qs)
        serializer = SchoolCalendarExceptionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
