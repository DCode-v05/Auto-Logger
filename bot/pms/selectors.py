"""Single source of truth for HTML selectors on iqube.therig.in.

If the site changes its HTML, the fix goes here — nowhere else.
All selectors are verified by `tests/test_selectors.py` against a real login fixture.
"""

# iQube login page
IQUBE_MS_LOGIN_BUTTON = 'a[href*="azuread-oauth2"]'

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
FORM_ACTIVITIES = '#id_activities_done'
FORM_TIME_SPENT = '#id_time_spent'
FORM_LOCATION = '#id_location'
FORM_LOCATION_OTHER = '#id_location_other, input[name="location_other"]'
FORM_REFERENCE_LINK = '#id_reference_link'
FORM_ATTACHMENT = 'input[type="file"][name="attachment"], input[type="file"]'
FORM_DESCRIPTION_TEXTAREA = '#id_description'  # CKEditor may wrap this
FORM_SUBMIT_BUTTON = 'button[type="submit"], input[type="submit"]'
FORM_ERROR_LIST = '.errorlist li, .invalid-feedback'

# PMS navigation
PMS_DAILY_LOG_CREATE_PATH = '/me/daily_log/create/'
PMS_DAILY_LOG_LIST_PATH = '/me/daily_log/'
PMS_ME_PATH = '/me/'

# Values for Location dropdown (as they appear in the <select>)
LOCATION_IQUBE = 'iQube'
LOCATION_HOME = 'Home/Hostel'
LOCATION_OTHER = 'Other (Specify)'
