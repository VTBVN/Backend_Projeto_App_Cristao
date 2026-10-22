"""Mongo persistence for accounts and opaque sessions; no local fallback."""
from typing import Protocol

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.errors import AuthUnavailable, EmailConflict


class AuthRepository(Protocol):
    def initialize(self): ...
    def find_session(self, token_hash): ...
    def insert_session(self, document): ...
    def rotate_csrf(self, token_hash, csrf_hash, now): ...
    def insert_user(self, document): ...


class UnavailableAuthRepository:
    def _unavailable(self, *args):
        raise AuthUnavailable()

    initialize = find_session = insert_session = rotate_csrf = insert_user = _unavailable


class MongoAuthRepository:
    def __init__(self, database):
        self.users = database['users']
        self.sessions = database['sessions']

    def initialize(self):
        try:
            self.users.create_index('email_normalized', unique=True, name='users_email_unique')
            self.sessions.create_index('token_hash', unique=True, name='sessions_token_unique')
            self.sessions.create_index('expires_at', expireAfterSeconds=0, name='sessions_expiry')
        except PyMongoError:
            raise AuthUnavailable() from None

    def find_session(self, token_hash):
        try:
            return self.sessions.find_one({'token_hash': token_hash})
        except PyMongoError:
            raise AuthUnavailable() from None

    def insert_session(self, document):
        try:
            self.sessions.insert_one(document)
        except PyMongoError:
            raise AuthUnavailable() from None

    def rotate_csrf(self, token_hash, csrf_hash, now):
        try:
            result = self.sessions.update_one(
                {'token_hash': token_hash, 'expires_at': {'$gt': now}},
                {'$set': {'csrf_hash': csrf_hash}})
            return result.matched_count == 1
        except PyMongoError:
            raise AuthUnavailable() from None

    def insert_user(self, document):
        try:
            self.users.insert_one(document)
        except DuplicateKeyError:
            raise EmailConflict() from None
        except PyMongoError:
            raise AuthUnavailable() from None
        return document
