from rest_framework import generics

from accounts.serializers import UserSummarySerializer


class MeView(generics.RetrieveAPIView):
    """GET /me/ — the current user (resolved from the Clerk JWT), in the same
    User summary shape used wherever a user is nested elsewhere. `id` matches
    the `driver`/`sender`/`raised_by`/`requested_by` ids in other responses.
    """

    serializer_class = UserSummarySerializer

    def get_object(self):
        return self.request.user
