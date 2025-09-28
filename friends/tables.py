import django_tables2 as tables
from django.db.models import F, Avg, Count, Q, Max
from django.utils.safestring import mark_safe
from django.urls import reverse

from app.tables import FloatColumn
from application.models import Application


class FriendInviteTable(tables.Table):
    select = tables.CheckBoxColumn(accessor='code', attrs={"th__input": {"onclick": "select_all(this)",
                                                                         'class': 'form-check-input'},
                                                           'td__input': {'class': 'form-check-input'}})
    vote_avg = FloatColumn(float_digits=3)
    pending = tables.Column(attrs={'td': {'class': 'pending'}})
    devpost = tables.Column(empty_values=(), verbose_name='Devpost')

    @staticmethod
    def get_queryset(queryset):
        return queryset.values('user__friendscode__code').annotate(
            code=F('user__friendscode__code'),
            vote_avg=Avg('vote__calculated_vote'),
            members=Count('user'),
            pending=Count('user', filter=Q(status=Application.STATUS_PENDING)),
            invited=Count('user', filter=Q(status=Application.STATUS_INVITED)),
            accepted=Count('user', filter=Q(status=Application.STATUS_CONFIRMED)),
            devpost=Max('user__friendscode__devpost_url'))

    def render_devpost(self, value):
        if value:
            return mark_safe(f'<a href="{value}" target="_blank" rel="noopener noreferrer">link</a>')
        return '-'

    def render_code(self, value):
        """Make the group code clickable to open the applications list filtered by this code."""
        try:
            type_param = self.request.GET.get('type') or 'Hacker'
        except Exception:
            type_param = 'Hacker'
        url = f"{reverse('application_list')}?type={type_param}&code={value}"
        return mark_safe(f'<a href="{url}">{value}</a>')

    class Meta:
        model = Application
        attrs = {'class': 'table table-striped'}
        fields = ('select', 'code', 'vote_avg', 'members', 'pending', 'invited', 'accepted', 'devpost')
        empty_text = 'No friends :\'('
        order_by = 'vote_avg'
        template_name = 'django_tables2/bootstrap5.html'
