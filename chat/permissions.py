from rest_framework.permissions import BasePermission

from chat.services import user_can_access_thread


class IsThreadParticipant(BasePermission):
    message = "You do not have access to this chat thread."

    def has_object_permission(self, request, view, obj):
        thread = obj if not hasattr(obj, "thread_id") else obj.thread
        return user_can_access_thread(request.user, thread.id)
