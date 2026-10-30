from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.middleware.csrf import get_token, rotate_token
from rest_framework.authentication import SessionAuthentication
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken


class LoginRateThrottle(AnonRateThrottle):
    """5 login attempts per minute per IP to limit brute-force."""
    rate = '5/minute'

ACCESS_COOKIE = 'ams_access'
REFRESH_COOKIE = 'ams_refresh'


class CsrfTokenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        response = Response({'csrfToken': get_token(request)})
        response['Cache-Control'] = 'no-store'
        return response


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
        domain=settings.COOKIE_DOMAIN,
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
            domain=settings.COOKIE_DOMAIN,
        )


class CookieLoginView(APIView):
    """
    POST /auth/cookie/login/
    Body: { username, password }
    On success sets ams_access and ams_refresh httpOnly cookies.
    Returns 200 with { "detail": "Login successful." }
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        SessionAuthentication().enforce_csrf(request)
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response(
                {'detail': 'username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            inactive_user = User.objects.filter(username=username, is_active=False).first()
            if inactive_user is not None and inactive_user.check_password(password):
                return Response(
                    {'detail': 'Account disabled.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            return Response(
                {'detail': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        rotate_token(request)
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
    authentication_classes = []
    throttle_classes = []  # exempt from global throttle

    def post(self, request):
        SessionAuthentication().enforce_csrf(request)
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE)
        if not raw_refresh:
            return Response(
                {'detail': 'No refresh token cookie found.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            serializer = TokenRefreshSerializer(data={'refresh': raw_refresh})
            serializer.is_valid(raise_exception=True)
        except (TokenError, InvalidToken) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        access = serializer.validated_data['access']
        refresh = serializer.validated_data.get('refresh')
        response = Response({'detail': 'Token refreshed.'}, status=status.HTTP_200_OK)
        if refresh:
            _set_token_cookies(response, access, refresh)
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
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE)
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass  # An invalid/already-revoked token must not prevent logout.
        response = Response({'detail': 'Logged out.'}, status=status.HTTP_200_OK)
        response.delete_cookie(ACCESS_COOKIE, path='/', domain=settings.COOKIE_DOMAIN)
        response.delete_cookie(REFRESH_COOKIE, path='/', domain=settings.COOKIE_DOMAIN)
        return response
