from decimal import Decimal

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from customers.models import Customer
from deals.models import Deal
from tasks.models import Task
from web.forms import CustomerForm, DealForm, TaskForm
from accounts.access import OrganizationRequiredMixin, OrganizationQuerysetMixin


class LandingView(TemplateView):
    template_name = 'web/landing.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('web:dashboard')
        return super().get(request, *args, **kwargs)


class DashboardView(OrganizationRequiredMixin, TemplateView):
    template_name = 'web/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        active = Deal.objects.filter(organization=self.organization).exclude(stage__in=[Deal.Stage.WON, Deal.Stage.LOST])
        pending = Task.objects.filter(organization=self.organization, status__in=[Task.Status.NEW, Task.Status.IN_PROGRESS])
        context.update(
            section='dashboard', today=today, customer_count=Customer.objects.filter(organization=self.organization).count(),
            active_deals=active.count(), active_amount=active.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            tasks_today=pending.filter(due_date=today).count(),
            overdue_tasks=pending.filter(due_date__lt=today).count(),
            pending_tasks=pending.count(),
            deal_stages=Deal.Stage.choices,
            recent_deals=Deal.objects.filter(organization=self.organization).select_related('customer')[:5],
            upcoming_tasks=pending.select_related('customer').filter(due_date__isnull=False).order_by('due_date', 'id')[:5],
        )
        return context


def return_to_list(request, route):
    # Only a query string is accepted; the destination is always our own route.
    query = request.POST.get('filters', '')
    target = reverse(route)
    if query and len(query) <= 4096 and not any(c in query for c in '\r\n#'):
        target += '?' + query
    return HttpResponseRedirect(target)


class DealStageView(OrganizationRequiredMixin, View):
    def post(self, request, pk):
        deal = get_object_or_404(Deal, pk=pk, organization=self.organization)
        stage = request.POST.get('stage')
        if stage not in Deal.Stage.values:
            messages.error(request, 'Выберите существующую стадию сделки.')
        elif stage != deal.stage:
            deal.stage = stage
            deal.save(update_fields=['stage', 'updated_at'])
            messages.success(request, f'Стадия сделки «{deal.title}»: {stage}.')
        if request.POST.get('source') == 'deals':
            return return_to_list(request, 'web:deals')
        return redirect('web:dashboard')


class TaskStatusView(OrganizationRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, organization=self.organization)
        status = request.POST.get('status')
        if status not in Task.Status.values:
            messages.error(request, 'Выберите существующий статус задачи.')
        elif status != task.status:
            task.status = status
            task.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'Статус задачи «{task.title}»: {status}.')
        return return_to_list(request, 'web:tasks')


class FilteredListView(OrganizationQuerysetMixin, ListView):
    paginate_by = 20
    context_object_name = 'records'
    section = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(section=self.section, search=self.request.GET.get('q', '').strip())
        return context


class CustomerListView(FilteredListView):
    model = Customer
    section = 'customers'
    template_name = 'web/customers.html'

    def get_queryset(self):
        records = super().get_queryset()
        query = self.request.GET.get('q', '').strip()
        if query:
            records = records.filter(Q(name__icontains=query) | Q(company_name__icontains=query)
                                     | Q(phone__icontains=query) | Q(email__icontains=query))
        return records


class DealListView(FilteredListView):
    model = Deal
    section = 'deals'
    template_name = 'web/deals.html'

    def get_queryset(self):
        records = super().get_queryset().select_related('customer')
        query = self.request.GET.get('q', '').strip()
        stage = self.request.GET.get('stage', '')
        if query:
            records = records.filter(Q(title__icontains=query) | Q(customer__name__icontains=query))
        if stage:
            records = records.filter(stage=stage)
        return records

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), 'stages': Deal.Stage.choices,
                'selected_stage': self.request.GET.get('stage', '')}


class TaskListView(FilteredListView):
    model = Task
    section = 'tasks'
    template_name = 'web/tasks.html'

    def get_queryset(self):
        records = super().get_queryset().select_related('customer', 'deal')
        query = self.request.GET.get('q', '').strip()
        if query:
            records = records.filter(Q(title__icontains=query) | Q(description__icontains=query)
                                     | Q(customer__name__icontains=query) | Q(deal__title__icontains=query))
        for field in ['status', 'priority']:
            value = self.request.GET.get(field, '')
            if value:
                records = records.filter(**{field: value})
        return records

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), 'statuses': Task.Status.choices,
                'priorities': Task.Priority.choices, 'today': timezone.localdate(),
                'selected_status': self.request.GET.get('status', ''),
                'selected_priority': self.request.GET.get('priority', '')}


class RecordDetailView(OrganizationQuerysetMixin, DetailView):
    template_name = 'web/detail.html'
    context_object_name = 'record'
    section = ''
    list_url = ''
    edit_name = ''
    delete_name = ''

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), 'section': self.section,
                'list_url': self.list_url, 'edit_name': self.edit_name,
                'delete_name': self.delete_name}


class CustomerDetailView(RecordDetailView):
    model = Customer
    section = 'customers'
    list_url = reverse_lazy('web:customers')
    edit_name = 'web:customer-edit'
    delete_name = 'web:customer-delete'

    def get_queryset(self):
        return super().get_queryset().prefetch_related('deals', 'tasks')


class DealDetailView(RecordDetailView):
    model = Deal
    section = 'deals'
    list_url = reverse_lazy('web:deals')
    edit_name = 'web:deal-edit'
    delete_name = 'web:deal-delete'

    def get_queryset(self):
        return super().get_queryset().select_related('customer').prefetch_related('tasks')


class TaskDetailView(RecordDetailView):
    model = Task
    section = 'tasks'
    list_url = reverse_lazy('web:tasks')
    edit_name = 'web:task-edit'
    delete_name = 'web:task-delete'

    def get_queryset(self):
        return super().get_queryset().select_related('customer', 'deal')


class EditorMixin(OrganizationQuerysetMixin, SuccessMessageMixin):
    template_name = 'web/form.html'
    success_message = 'Изменения сохранены.'

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'organization': self.organization}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(section=self.section, page_title=self.page_title, list_url=self.success_url)
        return context


class CustomerEditor(EditorMixin):
    model = Customer
    form_class = CustomerForm
    section = 'customers'
    success_url = reverse_lazy('web:customers')


class CustomerCreateView(CustomerEditor, CreateView):
    page_title = 'Новый клиент'


class CustomerUpdateView(CustomerEditor, UpdateView):
    page_title = 'Редактирование клиента'


class DealEditor(EditorMixin):
    model = Deal
    form_class = DealForm
    section = 'deals'
    success_url = reverse_lazy('web:deals')


class DealCreateView(DealEditor, CreateView):
    page_title = 'Новая сделка'


class DealUpdateView(DealEditor, UpdateView):
    page_title = 'Редактирование сделки'


class TaskEditor(EditorMixin):
    model = Task
    form_class = TaskForm
    section = 'tasks'
    success_url = reverse_lazy('web:tasks')


class TaskCreateView(TaskEditor, CreateView):
    page_title = 'Новая задача'


class TaskUpdateView(TaskEditor, UpdateView):
    page_title = 'Редактирование задачи'


class ConfirmDeleteView(OrganizationQuerysetMixin, SuccessMessageMixin, DeleteView):
    template_name = 'web/confirm_delete.html'
    success_message = 'Запись удалена.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(section=self.section, list_url=self.success_url)
        if self.section == 'customers':
            context['deal_count'] = self.object.deals.count()
        return context


class CustomerDeleteView(ConfirmDeleteView):
    model = Customer
    section = 'customers'
    success_url = reverse_lazy('web:customers')


class DealDeleteView(ConfirmDeleteView):
    model = Deal
    section = 'deals'
    success_url = reverse_lazy('web:deals')


class TaskDeleteView(ConfirmDeleteView):
    model = Task
    section = 'tasks'
    success_url = reverse_lazy('web:tasks')
