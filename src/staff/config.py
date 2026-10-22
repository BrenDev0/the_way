# Staff are Xplorers' own people. They sign in apart from every customer's account, for a
# shorter time, with a cookie of their own.
STAFF_SESSION_COOKIE_NAME = "staff_session"
STAFF_SESSION_TTL_SECONDS = 60 * 60 * 12

OWNER_INVITATION_TTL_SECONDS = 60 * 60 * 24 * 7
TOKEN_BYTES = 48

# No rule on what a staff password is (length, characters): whoever runs the create command
# picks it. The one limit is bcrypt's own: it cannot hash more than 72 bytes (a multi-byte
# character counts for more than one), so a longer one could never be stored.
MAX_STAFF_PASSWORD_BYTES = 72
