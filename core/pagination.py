from rest_framework.pagination import CursorPagination, PageNumberPagination


class DefaultPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TimeOrderedCursorPagination(CursorPagination):
    """For append-heavy, time-ordered data (chat messages, location pings)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"
