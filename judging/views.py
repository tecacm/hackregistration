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
from friends.models import FriendsCode

from .forms import ProjectForm, ProjectSearchForm, ReleaseWindowForm, ScoreForm
from .models import JudgingEvaluation, JudgingProject, JudgingReleaseWindow, JudgingRubric
from .services import (
    build_leaderboard,
    compute_track_standings,
    determine_track_winners,
    ensure_project_for_team_code,
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
        allowed_groups = ['Judge', 'Judges', 'Organizer', 'Organizers']
        if user.groups.filter(name__in=allowed_groups).exists():
            return True
        judge_like = user.groups.filter(name__icontains='judge').exists()
        organizer_like = user.groups.filter(name__icontains='organizer').exists()
        if judge_like or organizer_like:
            return True
        return user.application_set.actual().filter(type__name__iexact='Judge').exists()


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

    @staticmethod
    def _normalize_badge_value(raw: str) -> str:
        if not raw:
            return ''
        value = (raw or '').strip()
        if not value:
            return ''
        if '://' in value:
            try:
                from urllib.parse import parse_qs, urlparse

                parsed = urlparse(value)
                query_values = parse_qs(parsed.query).get('code')
                if query_values and query_values[0]:
                    value = query_values[0]
                else:
                    parts = [part for part in parsed.path.split('/') if part]
                    if parts:
                        value = parts[-1]
            except Exception:
                parts = [part for part in value.split('/') if part]
                if parts:
                    value = parts[-1]
        return value.strip()

    def _resolve_project(self, identifier: str):
        from django.utils.text import slugify

        normalized = (identifier or '').strip()
        if not normalized:
            return None, None

        edition_id = Edition.get_default_edition()

        def single_or_suggestions(queryset, label):
            matches = list(queryset[:6])
            if not matches:
                return None, None
            if len(matches) == 1:
                return matches[0], None
            suggestions = [f"{match.name} (table {match.table_location or _('n/a')})" for match in matches[:5]]
            return None, {'label': label, 'suggestions': suggestions}

        # Direct project id
        if normalized.isdigit():
            project = JudgingProject.objects.filter(
                pk=int(normalized),
                edition_id=edition_id,
                is_active=True,
            ).first()
            if project:
                return project, None

        # QR slug
        project = JudgingProject.objects.filter(
            qr_slug__iexact=normalized,
            edition_id=edition_id,
            is_active=True,
        ).first()
        if project:
            return project, None

        # Team code (with auto-creation)
        project = JudgingProject.objects.filter(
            friends_code__code__iexact=normalized,
            edition_id=edition_id,
            is_active=True,
        ).first()
        if project:
            return project, None
        project = ensure_project_for_team_code(normalized)
        if project:
            return project, None

        # Table location (allow "table" prefix)
        search_value = normalized
        if normalized.lower().startswith('table '):
            search_value = normalized.split(' ', 1)[1].strip()
        if search_value:
            project = JudgingProject.objects.filter(
                table_location__iexact=search_value,
                edition_id=edition_id,
                is_active=True,
            ).first()
            if project:
                return project, None

        # Exact project name
        project = JudgingProject.objects.filter(
            name__iexact=normalized,
            edition_id=edition_id,
            is_active=True,
        ).first()
        if project:
            return project, None

        # Fuzzy project name with suggestions
        project, details = single_or_suggestions(
            JudgingProject.objects.filter(
                name__icontains=normalized,
                edition_id=edition_id,
                is_active=True,
            ).order_by('name'),
            _('project name'),
        )
        if project or details:
            return project, details

        # Devpost metadata slug
        slug_candidate = slugify(normalized)
        if slug_candidate:
            project, details = single_or_suggestions(
                JudgingProject.objects.filter(
                    metadata__devpost_url__icontains=slug_candidate,
                    edition_id=edition_id,
                    is_active=True,
                ),
                _('Devpost link'),
            )
            if project or details:
                return project, details

        return None, None

    def post(self, request, *args, **kwargs):
        action = request.POST.get('lookup_action', 'badge')

        if action == 'team':
            team_code = (request.POST.get('team_code') or '').strip()
            if not team_code:
                messages.error(request, _('Enter a team code to continue.'))
                return self.get(request, *args, **kwargs)
            project = ensure_project_for_team_code(team_code)
            if project is None:
                messages.error(
                    request,
                    _('No team was found with code “%(code)s”. Double-check the value printed on the badge or team list.')
                    % {'code': team_code},
                )
                return self.get(request, *args, **kwargs)
            messages.info(
                request,
                _('Loaded %(project)s via team code.') % {'project': project.name},
            )
            return redirect('judging:score', pk=project.pk)

        if action == 'project':
            identifier = (request.POST.get('project_lookup') or '').strip()
            if not identifier:
                messages.error(request, _('Enter a project, table, or Devpost reference to continue.'))
                return self.get(request, *args, **kwargs)
            project, details = self._resolve_project(identifier)
            if project:
                messages.info(
                    request,
                    _('Loaded %(project)s via manual lookup.') % {'project': project.name},
                )
                return redirect('judging:score', pk=project.pk)
            if details:
                suggestions = details.get('suggestions') or []
                if suggestions:
                    messages.warning(
                        request,
                        _('Multiple matches for %(label)s. Refine your search. Suggestions: %(options)s')
                        % {'label': details['label'], 'options': '; '.join(suggestions)},
                    )
                else:
                    messages.warning(request, _('Multiple projects match that search. Please refine your query.'))
            else:
                messages.error(
                    request,
                    _('No project matched “%(identifier)s”. Try the team code, table number, or badge value again.')
                    % {'identifier': identifier},
                )
            return self.get(request, *args, **kwargs)

        qr_code = self._normalize_badge_value(request.POST.get('qr_code', ''))
        if not qr_code:
            messages.error(request, _('Enter a participant QR code or link to continue.'))
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
                project = ensure_project_for_team_code(slug)
                if project is None:
                    messages.error(request, _('We could not find a project or participant for this code.'))
                    return redirect('judging:dashboard')
            else:
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
                'judge__last_name', 'judge__first_name', 'judge__email'
            ),
        )
        return (
            JudgingProject.objects.select_related('edition', 'friends_code')
            .prefetch_related(evaluations_prefetch)
            .order_by('name')
        )


class TrackWinnersView(LoginRequiredMixin, OrganizerAccessMixin, TemplateView):
    template_name = 'judging/track_winners.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        editions = list(Edition.objects.order_by('-order'))
        if not editions:
            context.update({'editions': [], 'selected_edition': None, 'tracks': [], 'has_scores': False})
            return context

        requested_edition = self.request.GET.get('edition')
        if requested_edition:
            edition = get_object_or_404(Edition, pk=requested_edition)
        else:
            edition = editions[0]

        standings = compute_track_standings(edition, include_untracked=True)

        def display_label(track_value: str) -> str:
            if not track_value:
                return _('General')
            return track_value.replace('_', ' ').strip().title()

        tracks = []
        for track_key, entries in standings.items():
            if not entries:
                continue
            winner = entries[0]
            tracks.append({
                'key': track_key,
                'label': display_label(track_key),
                'entries': entries,
                'winner': winner,
            })

        tracks.sort(key=lambda item: item['label'].casefold())

        context.update(
            {
                'editions': editions,
                'selected_edition': edition,
                'tracks': tracks,
                'has_scores': bool(tracks),
            }
        )
        return context


class JudgeProjectDirectoryView(LoginRequiredMixin, JudgeAccessMixin, TemplateView):
    template_name = 'judging/judge_project_directory.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        edition_id = Edition.get_default_edition()

        assigned_codes = list(
            FriendsCode.objects
            .filter(track_assigned__isnull=False)
            .exclude(track_assigned='')
            .values_list('code', flat=True)
        )
        for code in assigned_codes:
            ensure_project_for_team_code(code)

        base_qs = (
            JudgingProject.objects
            .filter(edition_id=edition_id, is_active=True)
            .select_related('friends_code')
            .order_by('name')
        )

        track_choices = (
            base_qs.exclude(track='')
            .values_list('track', flat=True)
            .distinct()
        )
        normalized_choices = sorted({(track or '').strip() for track in track_choices if track})

        selected_track = (self.request.GET.get('track') or '').strip()
        projects = base_qs
        if selected_track:
            projects = projects.filter(track__iexact=selected_track)

        def track_label(value: str) -> str:
            if not value:
                return _('General')
            return value.replace('_', ' ').strip().title()

        projects = list(projects)
        project_rows = []
        for project in projects:
            metadata = project.metadata or {}
            devpost_url = metadata.get('devpost_url')
            if not devpost_url and project.friends_code:
                devpost_url = project.friends_code.devpost_url
            project_rows.append(
                {
                    'project': project,
                    'track_label': track_label(project.track),
                    'friends_code': project.friends_code.code if project.friends_code else '',
                    'devpost_url': devpost_url,
                }
            )

        context.update(
            {
                'projects': project_rows,
                'selected_track': selected_track,
                'available_tracks': [(track, track_label(track)) for track in normalized_choices],
            }
        )
        return context


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
