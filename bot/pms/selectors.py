"""Single source of truth for HTML selectors on iqube.therig.in.

If the site changes its HTML, the fix goes here — nowhere else.
All selectors are verified by `tests/test_selectors.py` against a real login fixture.
"""

# iQube login page — first matching selector wins
IQUBE_MS_LOGIN_BUTTON_CANDIDATES = [
    'a[href*="azuread-oauth2"]',
    'a[href*="/login/azuread"]',
    'a[href*="/login/microsoft"]',
    'a[href*="microsoft"]',
    'a[href*="azure"]',
    'button:has-text("Microsoft")',
    'a:has-text("Microsoft")',
    'a:has-text("Sign in with Microsoft")',
]
# Kept for back-compat
IQUBE_MS_LOGIN_BUTTON = IQUBE_MS_LOGIN_BUTTON_CANDIDATES[0]

# Microsoft login
MS_EMAIL_INPUT = 'input[type="email"][name="loginfmt"]'
MS_EMAIL_NEXT_BUTTON = 'input[type="submit"][value="Next"]'
MS_PASSWORD_INPUT = 'input[type="password"][name="passwd"]'
MS_PASSWORD_SUBMIT = 'input[type="submit"][value="Sign in"]'
MS_STAY_SIGNED_IN_YES = 'input[type="submit"][value="Yes"]'
MS_STAY_SIGNED_IN_NO = 'input[type="submit"][value="No"]'
MS_MFA_CODE_INPUT = 'input[name="otc"]'
MS_MFA_SUBMIT = 'input[type="submit"][value="Verify"], input[type="submit"][value="Sign in"]'
MS_MFA_NUMBER_MATCH_DISPLAY = '#idRichContext_DisplaySign'  # 2-digit number shown to user
MS_ERROR_BOX = '#usernameError, #passwordError, [role="alert"]'

# PMS Daily Log form (/me/daily_log/create/)
# Each list is tried in order; first visible match wins.
FORM_ACTIVITIES_CANDIDATES = [
    'input[name="activities_done"]',
    'input[name="activities"]',
    '#id_activities_done',
    '#activities_done',
    'textarea[name="activities_done"]',
]
FORM_TIME_SPENT_CANDIDATES = [
    'input[name="time_spent"]',
    'input[name="hours"]',
    'input[name="time"]',
    '#id_time_spent',
    '#time_spent',
]
FORM_LOCATION_CANDIDATES = [
    'select[name="location"]',
    '#id_location',
    '#location',
]
FORM_LOCATION_OTHER_CANDIDATES = [
    'input[name="location_other"]',
    'input[name="other_location"]',
    'input[name="specify"]',
    '#id_location_other',
    '#location_other',
]
FORM_REFERENCE_LINK_CANDIDATES = [
    'input[name="reference_link"]',
    'input[name="reference"]',
    'input[name="link"]',
    '#id_reference_link',
]
FORM_ATTACHMENT_CANDIDATES = [
    'input[type="file"][name="attachment"]',
    'input[type="file"][name="file"]',
    'input[type="file"]',
]
FORM_DESCRIPTION_CANDIDATES = [
    'textarea[name="description"]',
    '#id_description',
    '#description',
]
FORM_SUBMIT_BUTTON = 'button[type="submit"], input[type="submit"]'
FORM_ERROR_LIST = '.errorlist li, .invalid-feedback, .alert-danger'

# Back-compat (legacy, still referenced by some test code)
FORM_ACTIVITIES = FORM_ACTIVITIES_CANDIDATES[0]
FORM_TIME_SPENT = FORM_TIME_SPENT_CANDIDATES[0]
FORM_LOCATION = FORM_LOCATION_CANDIDATES[0]
FORM_LOCATION_OTHER = FORM_LOCATION_OTHER_CANDIDATES[0]
FORM_REFERENCE_LINK = FORM_REFERENCE_LINK_CANDIDATES[0]
FORM_ATTACHMENT = FORM_ATTACHMENT_CANDIDATES[0]
FORM_DESCRIPTION_TEXTAREA = FORM_DESCRIPTION_CANDIDATES[0]

# PMS navigation
PMS_DAILY_LOG_CREATE_PATH = '/me/daily_log/create/'
PMS_DAILY_LOG_LIST_PATH = '/me/daily_log/'
PMS_ME_PATH = '/me/'

# Values for Location dropdown (as they appear in the <select>)
LOCATION_IQUBE = 'iQube'
LOCATION_HOME = 'Home/Hostel'
LOCATION_OTHER = 'Other (Specify)'
