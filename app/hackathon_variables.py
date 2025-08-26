HACKATHON_NAME = 'HackMTY'
HACKATHON_DESCRIPTION = "Join us for Monterrey's hackathon. 36h."
HACKATHON_ORG = 'HackMTY'
HACKATHON_START_DATE = '24/10/2025'
HACKATHON_END_DATE = '26/10/2025'
HACKATHON_LOCATION = 'Monterrey'

HACKATHON_CONTACT_EMAIL = 'hello@hackmty.com'
HACKATHON_SOCIALS = {'Facebook': ('https://www.facebook.com/hackmty', 'bi-facebook'),
                     'Instagram': ('https://www.instagram.com/hackmty', 'bi-instagram'),
                     'Twitter': ('https://twitter.com/hackmty', 'bi-twitter'),
                     'Github': ('https://github.com/HackAssistant', 'bi-github'), }
if HACKATHON_CONTACT_EMAIL:
    HACKATHON_SOCIALS['Contact'] = ('mailto:' + HACKATHON_CONTACT_EMAIL, 'bi-envelope')

HACKATHON_LANDING = 'https://hackmty.com/'
REGEX_HACKATHON_ORGANIZER_EMAIL = r"^.*@hackmty\.com$"
HACKATHON_ORGANIZER_EMAILS = []
APP_NAME = 'HackMTY'
SERVER_EMAIL = 'HackMTY <server@hackmty.com>'
ADMINS = [('Admins', 'president@hackmty.com')]
HACKATHON_APPLICATIONS_OPEN = True

SUPPORTED_RESUME_EXTENSIONS = ['.pdf']
FRIENDS_MAX_CAPACITY = None

REQUIRE_PERMISSION_SLIP_TO_UNDER_AGE = True
SUPPORTED_PERMISSION_SLIP_EXTENSIONS = ['.pdf']
PARTICIPANT_CAN_UPLOAD_PERMISSION_SLIP = True

ATTRITION_RATE = 1.5
