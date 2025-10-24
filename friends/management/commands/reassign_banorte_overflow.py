import random

from django.core.management.base import BaseCommand

from friends.services import TrackReassignmentService


class Command(BaseCommand):
    help = 'Reassign overflow teams from Banorte-sponsored tracks to alternate preferences.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview the changes without updating the database or sending emails.',
        )
        parser.add_argument(
            '--skip-email',
            action='store_true',
            help='Do not send notification emails to reassigned teams.',
        )
        parser.add_argument(
            '--seed',
            type=int,
            help='Seed for the random number generator to obtain reproducible selections.',
        )

    def handle(self, *args, **options):
        rng = random.Random(options['seed']) if options.get('seed') is not None else None
        service = TrackReassignmentService(rng=rng)
        reassignments, skipped = service.run(
            dry_run=options['dry_run'],
            send_emails=not options['skip_email'],
        )

        if not reassignments:
            self.stdout.write(self.style.WARNING('No teams required reassignment.'))
        else:
            for entry in reassignments:
                pref = {2: 'second', 3: 'third'}.get(entry['preference_used'], 'alternate')
                self.stdout.write(
                    f"{entry['team_code']} moved from {entry['old_track_label']} to {entry['new_track_label']} "
                    f"(used {pref} preference, team size {entry['team_size']})"
                )
            if options['dry_run']:
                self.stdout.write(self.style.SUCCESS(f"Preview complete: {len(reassignments)} team(s) would be reassigned."))
            else:
                self.stdout.write(self.style.SUCCESS(f"Reassigned {len(reassignments)} team(s)."))

        if skipped:
            self.stdout.write('Teams not reassigned:')
            for entry in skipped:
                self.stdout.write(f"  {entry.get('team_code')}: {entry.get('reason')}")
