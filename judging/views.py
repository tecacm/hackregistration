from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from application.models import Edition

from .forms import ProjectForm, ProjectSearchForm, ReleaseWindowForm, ScoreForm
from .models import JudgingEvaluation, JudgingProject, JudgingReleaseWindow, JudgingRubric
from .services import (
    build_leaderboard,
    ensure_project_for_team_member,
    export_csv,
    judge_summary,
    release_evaluations,
    upsert_evaluation,
)


class JudgeAccessMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        return user.groups.filter(name__in=['Judge', 'Organizer']).exists()


class OrganizerAccessMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        return user.is_staff or user.groups.filter(name__in=['Organizer']).exists()


class JudgeDashboardView(LoginRequiredMixin, JudgeAccessMixin, TemplateView):
    template_name = 'judging/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        edition_id = self.request.GET.get('edition') or None
        projects = JudgingProject.objects.filter(is_active=True)
        if edition_id:
            projects = projects.filter(edition_id=edition_id)
        filter_form = ProjectSearchForm(self.request.GET or None)
        if filter_form.is_valid():
            projects = filter_form.filter_queryset(projects)
        projects = projects.select_related('edition').order_by('name')
        evaluations = (
            JudgingEvaluation.objects.filter(judge=self.request.user, project__in=projects)
            .select_related('project')
        )
        evaluation_map = {evaluation.project_id: evaluation for evaluation in evaluations}
        active_window = JudgingReleaseWindow.objects.filter(
            edition__in=projects.values('edition'),
            is_active=True,
        ).first()
        project_rows = [
            {
                'project': project,
                'evaluation': evaluation_map.get(project.id),
            }
            for project in projects
        ]

        context.update(
            {
                'project_rows': project_rows,
                'filter_form': filter_form,
                'active_window': active_window,
                'summary': judge_summary(self.request.user),
                'launch_url': reverse('judging:launch'),
                'judging_portal_url': getattr(settings, 'JUDGING_PORTAL_URL', '/judging/'),
                'judges_guide_url': reverse('event:judges_guide'),
            }
        )
        return context


class ScorePortalLandingView(LoginRequiredMixin, JudgeAccessMixin, TemplateView):
    template_name = 'judging/portal_landing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'judging_portal_url': getattr(settings, 'JUDGING_PORTAL_URL', '/judging/'),
        })
        return context

    def post(self, request, *args, **kwargs):
        qr_code = request.POST.get('qr_code', '').strip()
        if not qr_code:
            messages.error(request, _('Enter a participant QR code to continue.'))
            return self.get(request, *args, **kwargs)
        return redirect('judging:scan', slug=qr_code)


class ScanRedirectView(LoginRequiredMixin, JudgeAccessMixin, View):
    def get(self, request, slug):
        project = JudgingProject.objects.filter(qr_slug=slug, is_active=True).first()
        if project is None:
            User = get_user_model()
            user = User.objects.filter(qr_code=slug).first()
            if user is None:
                user_pk = User.decode_encoded_pk(slug)
                if user_pk:
                    user = User.objects.filter(pk=user_pk).first()
            if user is None:
                messages.error(request, _('We could not find a project or participant for this QR code.'))
                return redirect('judging:dashboard')

            project = ensure_project_for_team_member(user)
            if project is None:
                messages.error(
                    request,
                    _('This participant is not linked to a team yet. Ask the team to finalize their grouping.'),
                )
                return redirect('judging:dashboard')

        messages.info(request, _('Loaded %(project)s for scoring.') % {'project': project.name})
        return redirect('judging:score', pk=project.pk)


class ScoreProjectView(LoginRequiredMixin, JudgeAccessMixin, FormView):
    template_name = 'judging/score_form.html'
    form_class = ScoreForm

    def dispatch(self, request, *args, **kwargs):
        self.project = get_object_or_404(
            JudgingProject.objects.select_related('edition'),
            pk=kwargs['pk'],
            is_active=True,
        )
        self.rubric = JudgingRubric.active_for_edition(self.project.edition, track=self.project.track)
        if self.rubric is None:
            messages.error(request, _('No active rubric configured for this edition. Please contact organizers.'))
            return redirect('judging:dashboard')
        self.evaluation = JudgingEvaluation.objects.filter(
            project=self.project,
            judge=request.user,
            rubric=self.rubric,
        ).first()
        window = JudgingReleaseWindow.objects.filter(edition=self.project.edition, is_active=True).first()
        if window and not window.is_open:
            messages.warning(
                request,
                _('The judging window is currently closed. You can review previous notes but cannot submit new scores.'),
            )
            return redirect('judging:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial_scores = {}
        notes = ''
        if self.evaluation:
            initial_scores = self.evaluation.scores
            notes = self.evaluation.notes
        kwargs.update({'rubric': self.rubric, 'initial': {**initial_scores, 'notes': notes}})
        return kwargs

    def form_valid(self, form):
        submit = self.request.POST.get('action') == 'submit'
        upsert_evaluation(
            project=self.project,
            judge=self.request.user,
            scores=form.cleaned_scores(),
            notes=form.cleaned_data.get('notes', ''),
            submit=submit,
            rubric=self.rubric,
        )
        action_message = _('submitted') if submit else _('saved')
        messages.success(
            self.request,
            _('Evaluation %(action)s for %(project)s.')
            % {'action': action_message, 'project': self.project.name},
        )
        return redirect('judging:score', pk=self.project.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get('form')
        rubric_sections = []
        if form:
            for section in self.rubric.definition.get('sections', []):
                fields = []
                for criterion in section.get('criteria', []):
                    field_id = criterion.get('id')
                    if field_id in form.fields:
                        fields.append({'criterion': criterion, 'field': form[field_id]})
                rubric_sections.append({'section': section, 'fields': fields})
        context.update(
            {
                'project': self.project,
                'rubric': self.rubric,
                'evaluation': self.evaluation,
                'rubric_sections': rubric_sections,
            }
        )
        return context


class ProjectListView(LoginRequiredMixin, OrganizerAccessMixin, ListView):
    template_name = 'judging/manage_projects.html'
    context_object_name = 'projects'

    def get_queryset(self):
        evaluations_prefetch = Prefetch(
            'evaluations',
            queryset=JudgingEvaluation.objects.select_related('judge').order_by(
                'judge__last_name', 'judge__first_name', 'judge__username'
            ),
        )
        return (
            JudgingProject.objects.select_related('edition', 'friends_code')
            .prefetch_related(evaluations_prefetch)
            .order_by('name')
        )


class ProjectCreateView(LoginRequiredMixin, OrganizerAccessMixin, CreateView):
    template_name = 'judging/manage_project_form.html'
    form_class = ProjectForm
    success_url = reverse_lazy('judging:manage_projects')

    def form_valid(self, form):
        form.instance.edition_id = Edition.get_default_edition()
        messages.success(self.request, _('Project created.'))
        return super().form_valid(form)


class ProjectUpdateView(LoginRequiredMixin, OrganizerAccessMixin, UpdateView):
    template_name = 'judging/manage_project_form.html'
    form_class = ProjectForm
    success_url = reverse_lazy('judging:manage_projects')
    queryset = JudgingProject.objects.all()

    def form_valid(self, form):
        messages.success(self.request, _('Project updated.'))
        return super().form_valid(form)


class ProjectDeleteView(LoginRequiredMixin, OrganizerAccessMixin, View):
    def post(self, request, *args, **kwargs):
        project = get_object_or_404(JudgingProject, pk=kwargs['pk'])
        project_name = project.name
        project.delete()
        messages.success(request, _('Project "%(project)s" deleted.') % {'project': project_name})
        return redirect('judging:manage_projects')


class ToggleScoresPublicationView(LoginRequiredMixin, OrganizerAccessMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            edition = Edition.objects.get(pk=Edition.get_default_edition())
        except Edition.DoesNotExist:
            messages.error(request, _('Edition not found.'))
            return redirect('judging:release_window')

        publish_param = request.POST.get('publish')
        if publish_param not in {'0', '1'}:
            publish = not edition.judging_scores_public
        else:
            publish = publish_param == '1'

        edition.judging_scores_public = publish
        edition.save(update_fields=['judging_scores_public'])

        if publish:
            messages.success(
                request,
                _('Judging results are now visible to teams on the friends portal.'),
            )
        else:
            messages.info(
                request,
                _('Team-facing judging results have been hidden.'),
            )
        return redirect('judging:release_window')


class ReleaseWindowView(LoginRequiredMixin, OrganizerAccessMixin, FormView):
    template_name = 'judging/release_window.html'
    form_class = ReleaseWindowForm
    success_url = reverse_lazy('judging:release_window')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        window = JudgingReleaseWindow.objects.filter(edition_id=Edition.get_default_edition()).first()
        if window:
            kwargs['instance'] = window
        return kwargs

    def form_valid(self, form):
        window = form.save(commit=False)
        if window.edition_id is None:
            window.edition_id = Edition.get_default_edition()
        window.save()
        messages.success(self.request, _('Release window saved.'))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        edition = Edition.objects.get(pk=Edition.get_default_edition())
        context['windows'] = JudgingReleaseWindow.objects.filter(edition=edition).order_by('-opens_at')
        context['leaderboard'] = list(build_leaderboard(edition))
        context['release_confirm_message'] = _('Release all submitted evaluations?')
        context['edition'] = edition
        return context


class ReleaseActionView(LoginRequiredMixin, OrganizerAccessMixin, View):
    def post(self, request, *args, **kwargs):
        window = get_object_or_404(JudgingReleaseWindow, pk=kwargs['pk'])
        released = release_evaluations(window, actor=request.user)
        messages.success(request, _('Released %(count)s evaluations.') % {'count': released})
        return redirect('judging:release_window')


class ExportCSVView(LoginRequiredMixin, OrganizerAccessMixin, View):
    def get(self, request, *args, **kwargs):
        edition = Edition.objects.get(pk=Edition.get_default_edition())
        buffer = export_csv(edition)
        response = HttpResponse(buffer.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="judging-{timezone.now():%Y%m%d%H%M}.csv"'
        return response
