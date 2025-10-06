from django.conf import settings
from django.utils.translation import gettext_lazy as _

LEVELS_OF_STUDY = [
	('Less than Secondary / High School', _('Less than Secondary / High School')),
	('Secondary / High School', _('Secondary / High School')),
	('Undergraduate University (2 year - community college or similar)', _('Undergraduate University (2 year - community college or similar)')),
	('Undergraduate University (3+ year)', _('Undergraduate University (3+ year)')),
	('Graduate University (Masters, Professional, Doctoral, etc)', _('Graduate University (Masters, Professional, Doctoral, etc)')),
	('Code School / Bootcamp', _('Code School / Bootcamp')),
	('Other Vocational / Trade Program or Apprenticeship', _('Other Vocational / Trade Program or Apprenticeship')),
	('Post Doctorate', _('Post Doctorate')),
	('Other', _('Other')),
	("I'm not currently a student", _("I'm not currently a student")),
	('Prefer not to answer', _('Prefer not to answer')),
]

DEFAULT_JUDGE_TYPE_CHOICES = [
	('technical', _('Technical / Engineering')),
	('product', _('Product / UX / Research')),
	('business', _('Business / Strategy / Operations')),
	('sponsor', _('Sponsor / Partner / Donor')),
	('other', _('Other / Generalist')),
]

JUDGE_TYPE_CHOICES = getattr(settings, 'JUDGE_TYPE_CHOICES', DEFAULT_JUDGE_TYPE_CHOICES)
