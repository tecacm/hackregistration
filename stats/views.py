import os
from io import BytesIO
from zipfile import ZipFile

from django.conf import settings
from django.http import Http404, JsonResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from app.mixins import TabsViewMixin
from application.models import Application, Edition
from stats import filters
from stats import stats
from stats.mixins import StatsPermissionRequiredMixin
from stats.utils import cache_stats
from user.mixins import IsOrganizerOrSponsorMixin
from user.models import User


MODELS = ['user', 'application']


class StatsHome(IsOrganizerOrSponsorMixin, View):
    def get(self, request, *args, **kwargs):
        final_model = MODELS[0]
        if not request.user.has_perms(['stats.view_stats']):
            for model in MODELS:
                if request.user.has_perms(['stats.view_stats_%s' % model.lower()]):
                    final_model = model
        return redirect(reverse('stats', kwargs={'model': final_model}))


class StatsMixin:
    def get_filter_class(self, model_name):
        filter_class = getattr(filters, model_name + 'StatsFilter', None)
        if filter_class is None:
            raise Http404()
        return filter_class

    def get_stats_class(self, model_name):
        stats_class = getattr(stats, model_name + 'Stats', None)
        if stats_class is None:
            raise Http404()
        return stats_class


class StatsView(StatsPermissionRequiredMixin, TabsViewMixin, StatsMixin, TemplateView):
    template_name = 'stats.html'
    permission_required = ['stats.view_stats']

    def get_current_tabs(self, **kwargs):
        all_perm = self.request.user.has_perms(self.permission_required)
        return [(item.title() + 's', reverse('stats', kwargs={'model': item})) for item in MODELS
                if all_perm or self.request.user.has_perms(['stats.view_stats_%s' % item.lower()])]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        model_name = self.kwargs.get('model', '').lower().title()
        filter_class = self.get_filter_class(model_name)
        stats_class = self.get_stats_class(model_name)
        user = self.request.user
        can_download = False
        if user.is_authenticated:
            try:
                can_download = user.is_organizer() or user.groups.filter(name='Sponsor').exists()
            except Exception:
                can_download = False
        context.update({'filter': filter_class(), 'name': model_name, 'stats': stats_class(), 'can_download': can_download})
        return context


def get_application_queryset():
    edition = Edition.get_default_edition()
    return Application.objects.filter(edition=edition)


class StatsDataView(StatsPermissionRequiredMixin, StatsMixin, View):
    permission_required = ['stats.view_stats']
    queryset = {'user': User.objects.filter(is_active=True), 'application': get_application_queryset}

    @cache_stats
    def get_queryset(self, model_name):
        queryset = self.queryset.get(model_name.lower())
        if callable(queryset):
            queryset = queryset()
        return list(queryset)

    def get_stats(self, model_name, filter_class, stats_class):
        model_list = self.get_queryset(model_name, force_update=self.request.GET.get('update_cache', None) is not None)
        model_filter = filter_class(self.request.GET)
        if model_filter.form.is_valid():
            model_list = model_filter.filter_list(model_list)
            data = stats_class().to_json(model_list)
            data['updated_time'] = self.get_queryset.get_cache_time(model_name)
            data['total'] = len(model_list)
            return data
        return {}

    def get(self, request, *args, **kwargs):
        model_name = kwargs.get('model', '').lower().title()
        filter_class = self.get_filter_class(model_name)
        stats_class = self.get_stats_class(model_name)
        data = self.get_stats(model_name, filter_class, stats_class)
        return JsonResponse(data)


class StatsDownloadResumesView(StatsPermissionRequiredMixin, StatsMixin, View):
    permission_required = ['stats.view_stats']

    def get(self, request, *args, **kwargs):
        model_name = kwargs.get('model', '').lower().title()
        if model_name != 'Application':
            raise Http404()
        # Optional filters might be applied in future; for now, download all actual applications for current type
        app_type = request.GET.get('type', 'Hacker')
        qs = get_application_queryset().filter(type__name=app_type)
        s = BytesIO()
        added = 0
        with ZipFile(s, 'w') as zf:
            for app in qs:
                data = getattr(app, 'form_data', {}) or {}
                # Respect resume_share flag
                if not data.get('resume_share', False):
                    continue
                resume = data.get('resume') or data.get('cv') or data.get('curriculum')
                if not resume:
                    for k, v in data.items():
                        if isinstance(v, dict) and v.get('type') == 'file':
                            resume = v
                            break
                if not resume:
                    continue
                try:
                    path_value = resume.get('path') if isinstance(resume, dict) else resume.get('path')
                    if not path_value:
                        continue
                    file_path = path_value if path_value.startswith(settings.MEDIA_ROOT) else os.path.join(settings.MEDIA_ROOT, path_value)
                except Exception:
                    continue
                if not os.path.isfile(file_path):
                    continue
                _, fname = os.path.split(file_path)
                arcname = os.path.join('resumes', f"{app.uuid}_{fname}")
                try:
                    zf.write(file_path, arcname)
                    added += 1
                except OSError:
                    pass
        resp = HttpResponse(s.getvalue(), content_type='application/x-zip-compressed')
        resp['Content-Disposition'] = 'attachment; filename=resumes_%s.zip' % app_type
        resp['X-Total-Files'] = str(added)
        return resp
