from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from ...core.models import Cashdesk
from .utils import troubleshooter_user_required


@troubleshooter_user_required
def main_view(request: HttpRequest) -> HttpResponse:
    ctx = {}

    sessions = []
    for c in Cashdesk.objects.filter(is_active=True).order_by('name'):
        for sess in c.get_active_sessions():
            sess.current_items = sess.get_current_items()
            sessions.append(sess)

    ctx['sessions'] = sessions

    return render(request, 'troubleshooter/main.html', ctx)
