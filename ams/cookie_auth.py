from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

ACCESS_COOKIE = 'ams_access'


class JWTCookieAuthentication(JWTAuthentication):
    """
    Reads the JWT access token from an httpOnly cookie (ams_access) instead
    of the Authorization header. Falls back to header-based auth so that
    the DRF browsable API and any non-browser clients still work.
    """

    def authenticate(self, request):
        if self.get_header(request) is not None:
            return super().authenticate(request)
        raw_token = request.COOKIES.get(ACCESS_COOKIE)
        if raw_token is None:
            return super().authenticate(request)

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
        except (InvalidToken, TokenError):
            # Corrupt / expired cookie — let the request fall through as
            # unauthenticated rather than raising immediately, so the 401
            # handler can trigger a client-side refresh.
            return None
        SessionAuthentication().enforce_csrf(request)
        return user, validated_token
