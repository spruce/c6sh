from typing import Union

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.db.models import QuerySet, Sum
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.utils.translation import ugettext as _
from django.views.generic import DetailView
from django.views.generic.list import ListView

from c6sh.core.utils.flow import FlowError, reverse_session

from .. import checks
from ...core.models import Cashdesk, CashdeskSession, ItemMovement, User
from ..forms import (
    ItemMovementFormSetHelper, SessionBaseForm, get_form_and_formset,
)
from ..report import generate_report
from .utils import BackofficeUserRequiredMixin, backoffice_user_required


@backoffice_user_required
def new_session(request: HttpRequest) -> Union[HttpResponse, HttpResponseRedirect]:
    form, formset = get_form_and_formset(initial_form={'backoffice_user': request.user})

    if request.method == 'POST':
        form, formset = get_form_and_formset(request=request)

        if form.is_valid() and formset.is_valid():
            session = CashdeskSession.objects.create(
                cashdesk=form.cleaned_data['cashdesk'],
                user=form.cleaned_data['user'],
                start=now(),
                cash_before=form.cleaned_data['cash_before'],
                backoffice_user_before=form.cleaned_data['backoffice_user'],
            )
            for f in formset:
                item = f.cleaned_data.get('item')
                amount = f.cleaned_data.get('amount')
                if item and amount and amount > 0:
                    ItemMovement.objects.create(
                        item=item,
                        session=session,
                        amount=amount,
                        backoffice_user=form.cleaned_data['backoffice_user'],
                    )
            messages.success(request, _('Session has been created.'))
            return redirect('backoffice:main')

        else:
            messages.error(request, _('Session could not be created. Please review the data.'))

    elif request.method == 'GET':
        param = request.GET.get('desk')
        if param:
            try:
                initial_form = {
                    'cashdesk': Cashdesk.objects.get(pk=int(param)),
                    'backoffice_user': request.user,
                }
                form, _ignored = get_form_and_formset(initial_form=initial_form)
            except:
                pass

    return render(request, 'backoffice/new_session.html', {
        'form': form,
        'formset': formset,
        'helper': ItemMovementFormSetHelper(),
        'users': User.objects.values_list('username', flat=True),
        'backoffice_users': User.objects.filter(is_backoffice_user=True).values_list('username', flat=True),
    })


class SessionListView(LoginRequiredMixin, BackofficeUserRequiredMixin, ListView):
    """ Implements only a list of active sessions for now. Ended sessions will
    be visible in the reports view """
    model = CashdeskSession
    template_name = 'backoffice/session_list.html'
    context_object_name = 'cashdesks'

    def get_queryset(self) -> QuerySet:
        return Cashdesk.objects.filter(is_active=True).order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx['check_errors'] = checks.all_errors()
        return ctx


class ReportListView(LoginRequiredMixin, BackofficeUserRequiredMixin, ListView):
    """ List of old sessions """
    model = CashdeskSession
    template_name = 'backoffice/report_list.html'
    context_object_name = 'sessions'
    paginate_by = 25

    def get_queryset(self) -> QuerySet:
        return CashdeskSession.objects.filter(end__isnull=False).order_by('-end')


class SessionDetailView(BackofficeUserRequiredMixin, DetailView):
    queryset = CashdeskSession.objects.all()
    template_name = 'backoffice/session_detail.html'
    context_object_name = 'session'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['url'] = self.request.build_absolute_uri('/')
        return ctx


@backoffice_user_required
def resupply_session(request: HttpRequest, pk: int) -> Union[HttpResponse, HttpResponseRedirect]:
    """ TODO: show approximate current amounts of items? """
    session = get_object_or_404(CashdeskSession, pk=pk)
    initial_form = {
        'cashdesk': session.cashdesk,
        'user': session.user,
        'backoffice_user': request.user,
        'cash_before': 0,
    }
    form, formset = get_form_and_formset(initial_form=initial_form)

    if request.method == 'POST':
        form, formset = get_form_and_formset(request=request)

        if formset.is_valid() and form.is_valid():
            for f in formset:
                item = f.cleaned_data.get('item')
                amount = f.cleaned_data.get('amount')
                if item and amount:
                    ItemMovement.objects.create(
                        item=item,
                        session=session,
                        amount=amount,
                        backoffice_user=form.cleaned_data['backoffice_user'],
                    )
            messages.success(request, _('Products have been added to the cashdesk.'))
            return redirect('backoffice:session-detail', pk=pk)

        elif formset.errors:
            messages.error(request, _('Error: Please review the data.'))

    form.fields['user'].widget.attrs['readonly'] = True
    form.fields['cashdesk'].widget.attrs['readonly'] = True
    form.fields['cash_before'].widget = forms.HiddenInput()

    return render(request, 'backoffice/resupply_session.html', {
        'formset': formset,
        'helper': ItemMovementFormSetHelper(),
        'form': form,
        'backoffice_users': User.objects.filter(is_backoffice_user=True).values_list('username', flat=True),
    })


@backoffice_user_required
def reverse_session_view(request: HttpRequest, pk: int) -> Union[HttpRequest, HttpResponseRedirect]:
    session = get_object_or_404(CashdeskSession, pk=pk)

    if request.method == 'POST':
        try:
            reverse_session(session)
        except FlowError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _('All transactions in the session have been cancelled.'))
        return redirect('backoffice:session-detail', pk=pk)

    elif request.method == 'GET':
        return render(request, 'backoffice/reverse_session.html', {
            'session': session,
        })


@backoffice_user_required
def end_session(request: HttpRequest, pk: int) -> Union[HttpRequest, HttpResponseRedirect]:
    session = get_object_or_404(CashdeskSession, pk=pk)
    item_data = session.get_current_items()
    cash_total = session.get_cash_transaction_total()

    if request.method == 'POST':
        form, formset = get_form_and_formset(request=request, extra=0)
        if form.is_valid() and formset.is_valid():
            if session.end:
                # This is not optimal, but our data model does not have a way of tracking
                # cash movement over time.
                session.cash_after = form.cleaned_data.get('cash_before')
                session.backoffice_user_after = form.cleaned_data.get('backoffice_user')
                session.save(update_fields=['cash_after', 'backoffice_user_after'])
            else:
                session.end = now()
                session.backoffice_user_after = form.cleaned_data.get('backoffice_user')
                session.cash_after = form.cleaned_data.get('cash_before')
                session.save(update_fields=['backoffice_user_after', 'cash_after', 'end'])
                messages.success(request, 'Session wurde beendet.')

            # It is important that we do this *after* we set session.end as the date of this movement
            # will be used in determining this as the final item takeout *after* the session.
            if not session.end:  # End session
                for f in formset:
                    item = f.cleaned_data.get('item')
                    amount = f.cleaned_data.get('amount')
                    if item and amount and amount:
                        ItemMovement.objects.create(
                            item=item,
                            session=session,
                            amount=-amount,
                            backoffice_user=form.cleaned_data['backoffice_user'],
                        )
            else:  # adjust end amounts
                item_amounts = session.item_movements.values('item').annotate(total=Sum('amount'))
                item_amounts = {
                    d['item']: d
                    for d in session.get_current_items()
                }
                for f in formset:
                    item = f.cleaned_data.get('item')
                    amount = f.cleaned_data.get('amount')
                    previous_amount = item_amounts[item]['final_movements']
                    if item and amount and amount:
                        ItemMovement.objects.create(
                            item=item,
                            session=session,
                            amount=previous_amount - amount,
                            backoffice_user=form.cleaned_data['backoffice_user'],
                        )

            generate_report(session)
            return redirect('backoffice:session-report', pk=pk)
        else:
            messages.error(request, _('Session could not be ended: Please review the data.'))

    elif request.method == 'GET':
        if session.end:
            msg = _('This session has ended already. Filling out this form will produce a corrected report. ')
            messages.warning(request, msg)

        form, formset = get_form_and_formset(
            extra=0,
            initial_form={'cashdesk': session.cashdesk, 'user': session.user, 'backoffice_user': request.user, 'cash_before': session.cash_after},
            initial_formset=[{'item': d['item'], 'amount': d['final_movements']} for d in item_data],
        )

    for f, item_data in zip(formset, item_data):
        f.product_label = item_data

    return render(request, 'backoffice/end_session.html', {
        'session': session,
        'form': form,
        'formset': formset,
        'cash': {'initial': session.cash_before, 'transactions': cash_total},
        'backoffice_users': User.objects.filter(is_backoffice_user=True).values_list('username', flat=True),
    })


@backoffice_user_required
def session_report(request: HttpRequest, pk: int) -> Union[HttpResponse, HttpResponseRedirect]:
    session = get_object_or_404(CashdeskSession, pk=pk)
    report_path = session.get_report_path()

    if not report_path:
        report_path = generate_report(session)

    response = HttpResponse(content=default_storage.open(report_path, 'rb'))
    response['Content-Type'] = 'application/pdf'
    response['Content-Disposition'] = 'inline; filename=sessionreport-{}.pdf'.format(session.pk)
    return response


@backoffice_user_required
def move_session(request: HttpRequest, pk: int) -> Union[HttpRequest, HttpResponseRedirect]:
    session = get_object_or_404(CashdeskSession, pk=pk)

    if session.end:
        messages.error(request, _('Session has already ended and cannot be moved.'))

    if request.method == 'POST':
        form = SessionBaseForm(request.POST, prefix='session')

        if form.is_valid():
            session.cashdesk = form.cleaned_data.get('cashdesk')
            session.save(update_fields=['cashdesk'])
            messages.success(request, _('Session has been moved.'))
        else:
            messages.error(request, _('Session could not be moved!'))
            return redirect('backoffice:session-detail', pk=pk)

    elif request.method == 'GET':
        form = SessionBaseForm(
            prefix='session',
            initial={
                'cashdesk': session.cashdesk,
                'user': session.user,
                'backoffice_user': session.backoffice_user_before,
                'cash_before': session.cash_before,
            },
        )

    form.fields['user'].widget.attrs['readonly'] = True
    form.fields['backoffice_user'].widget = forms.HiddenInput()
    form.fields['cash_before'].widget = forms.HiddenInput()

    return render(request, 'backoffice/move_session.html', {
        'session': session,
        'form': form,
    })
