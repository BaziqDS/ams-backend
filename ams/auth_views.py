from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken


class LoginRateThrottle(AnonRateThrottle):
    """5 login attempts per minute per IP to limit brute-force."""
    rate = '5/minute'

ACCESS_COOKIE = 'ams_access'
REFRESH_COOKIE = 'ams_refresh'


def _set_token_cookies(response, access_token: str, refresh_token: str | None = None):
    secure = settings.COOKIE_SECURE
    samesite = 'Lax'

    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()),
        httponly=True,
        secure=secure,
        samesite=samesite,
        path='/',
    )
    if refresh_token is not None:
        response.set_cookie(
            REFRESH_COOKIE,
            refresh_token,
            max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
            httponly=True,
            secure=secure,
            samesite=samesite,
            path='/',
        )


class CookieLoginView(APIView):
    """
    POST /auth/cookie/login/
    Body: { username, password }
    On success sets ams_access and ams_refresh httpOnly cookies.
    Returns 200 with { "detail": "Login successful." }
    """
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response(
                {'detail': 'username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {'detail': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        response = Response({'detail': 'Login successful.'}, status=status.HTTP_200_OK)
        _set_token_cookies(response, str(refresh.access_token), str(refresh))
        return response


class CookieRefreshView(APIView):
    """
    POST /auth/cookie/refresh/
    Reads ams_refresh cookie, returns a new ams_access cookie.
    No throttle — a valid refresh cookie is required, so there is no
    brute-force risk, and the global anonymous throttle would wrongly
    block legitimate silent refreshes.
    """
    permission_classes = [AllowAny]
    throttle_classes = []  # exempt from global throttle

    def post(self, request):
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE)
        if not raw_refresh:
            return Response(
                {'detail': 'No refresh token cookie found.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(raw_refresh)
            access = str(refresh.access_token)
        except (TokenError, InvalidToken) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        response = Response({'detail': 'Token refreshed.'}, status=status.HTTP_200_OK)
        if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
            _set_token_cookies(response, access, str(refresh))
        else:
            _set_token_cookies(response, access)
        return response


class CookieLogoutView(APIView):
    """
    POST /auth/cookie/logout/
    Clears auth cookies. Requires authentication so accidental calls from
    unauthenticated clients don't silently fail in a confusing way.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = Response({'detail': 'Logged out.'}, status=status.HTTP_200_OK)
        response.delete_cookie(ACCESS_COOKIE, path='/')
        response.delete_cookie(REFRESH_COOKIE, path='/')
        return response
