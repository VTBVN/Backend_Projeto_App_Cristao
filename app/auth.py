"""Anonymous CSRF sessions and public registration."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest
from werkzeug.security import generate_password_hash

from app.errors import ApiError, EmailConflict


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def configure_auth(app):
    origin = app.config['APP_ORIGIN']
    parts = urlsplit(origin)
    if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
            or parts.password or parts.path or parts.query or parts.fragment):
        raise ValueError('APP_ORIGIN deve ser uma origem HTTP(S), sem caminho.')
    secure = app.config['SESSION_COOKIE_SECURE']
    if not isinstance(secure, bool):
        raise ValueError('SESSION_COOKIE_SECURE deve ser booleano.')
    if not secure and not (app.config['APP_ENV'] == 'testing' or (
            app.config['APP_ENV'] == 'development' and parts.scheme == 'http'
            and parts.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('Cookie sem Secure permitido somente em testes ou localhost HTTP.')
    if app.config['ANONYMOUS_SESSION_TTL_SECONDS'] != 1800:
        raise ValueError('Sessão anônima deve durar 1800 segundos.')


def now():
    clock = current_app.config.get('AUTH_CLOCK')
    return clock() if clock else datetime.now(timezone.utc)


def repository():
    return current_app.extensions['auth_repository']


def check_origin():
    if 'Origin' in request.headers and request.headers['Origin'] != current_app.config['APP_ORIGIN']:
        raise ApiError(403, 'csrf_invalid', 'Origem inválida.')


def read_session(at):
    token = request.cookies.get('app_session', '')
    if not token or len(token) > 256:
        return None
    session = repository().find_session(digest(token))
    if session is None or session['expires_at'] <= at:
        return None
    return session


def require_csrf():
    check_origin()
    session = read_session(now())
    token = request.headers.get('X-CSRF-Token', '')
    if (session is None or not token or len(token) > 256
            or not hmac.compare_digest(digest(token), session['csrf_hash'])):
        raise ApiError(403, 'csrf_invalid', 'Sessão e token CSRF válidos são obrigatórios.')


def validate_user(payload):
    if not isinstance(payload, dict) or set(payload) != {'name', 'email', 'password'}:
        raise ApiError(400, 'validation_error', 'Dados inválidos.')
    name, email, password = (payload[key] for key in ('name', 'email', 'password'))
    if not all(isinstance(value, str) for value in (name, email, password)):
        raise ApiError(400, 'validation_error', 'Dados inválidos.')
    try:
        for value in (name, email, password):
            value.encode('utf-8', errors='strict')
    except UnicodeEncodeError:
        raise ApiError(400, 'validation_error', 'Dados inválidos.') from None
    name, email = name.strip(), email.strip().lower()
    local, separator, domain = email.rpartition('@')
    valid_email = (separator and len(local) <= 64 and len(email) <= 254
                   and re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
                   and not local.startswith('.') and not local.endswith('.') and '..' not in local
                   and len(domain.split('.')) >= 2
                   and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                           for label in domain.split('.')))
    if not (2 <= len(name) <= 80 and valid_email and 12 <= len(password) <= 128):
        raise ApiError(400, 'validation_error', 'Dados inválidos.')
    return name, email, password


auth = Blueprint('auth', __name__, url_prefix='/api')


@auth.get('/auth/csrf')
def csrf():
    check_origin()
    at, csrf_token = now(), secrets.token_urlsafe(32)
    session = read_session(at)
    session_token = None
    if session is not None:
        if not repository().rotate_csrf(session['token_hash'], digest(csrf_token), at):
            session = None
    if session is None:
        session_token = secrets.token_urlsafe(32)
        session = {'token_hash': digest(session_token), 'csrf_hash': digest(csrf_token),
                   'created_at': at, 'expires_at': at + timedelta(seconds=1800)}
        repository().insert_session(session)
    response = jsonify(data={'csrf_token': csrf_token})
    if session_token is not None:
        response.set_cookie('app_session', session_token, max_age=1800, httponly=True,
                            secure=current_app.config['SESSION_COOKIE_SECURE'],
                            samesite='Lax', path='/')
    return response


@auth.post('/users')
def register():
    require_csrf()
    try:
        payload = request.get_json(silent=False) if request.is_json else None
    except BadRequest:
        raise ApiError(400, 'validation_error', 'JSON inválido.') from None
    name, email, password = validate_user(payload)
    user = {'_id': ObjectId(), 'name': name, 'email_normalized': email,
            'password_hash': generate_password_hash(password, method='scrypt'),
            'bio': '', 'role': 'user', 'created_at': now()}
    try:
        repository().insert_user(user)
    except EmailConflict:
        raise ApiError(409, 'email_conflict', 'E-mail já cadastrado.') from None
    response = jsonify(data={'id': str(user['_id']), 'name': user['name'], 'email': email,
                             'bio': '', 'role': 'user',
                             'created_at': user['created_at'].isoformat().replace('+00:00', 'Z')})
    response.status_code = 201
    response.headers['Location'] = '/api/users/' + str(user['_id'])
    return response
