from django.core.management.base import BaseCommand

from friends.services import TrackAssignmentService


class Command(BaseCommand):
    help = 'Assign tracks to teams based on submitted preferences and available capacity.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview assignments without saving changes or sending emails.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of teams to assign in this run.',
        )
        parser.add_argument(
            '--skip-email',
            action='store_true',
            help='Assign tracks without sending notification emails.',
        )

    def handle(self, *args, **options):
        service = TrackAssignmentService()
        assignments, skipped = service.run(
            dry_run=options['dry_run'],
            limit=options.get('limit'),
            send_emails=not options['skip_email'],
        )

        if not assignments:
            self.stdout.write(self.style.WARNING('No teams were assigned.'))
        else:
            preference_map = {1: 'first', 2: 'second', 3: 'third'}
            for assignment in assignments:
                pref_label = preference_map.get(assignment['preference_used'], 'unknown')
                self.stdout.write(
                    f"{assignment['team_code']} -> {assignment['track_label']} "
                    f"(used {pref_label} preference, team size {assignment['team_size']})"
                )
            self.stdout.write(self.style.SUCCESS(f"Assigned {len(assignments)} team(s)."))

        if skipped:
            self.stdout.write('Skipped teams:')
            for entry in skipped:
                reason = entry.get('reason', 'unknown')
                self.stdout.write(f"  {entry.get('team_code')}: {reason}")
