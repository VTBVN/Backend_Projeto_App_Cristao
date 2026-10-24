"""Mongo persistence for accounts and opaque sessions; no local fallback."""
from typing import Protocol

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.errors import AuthUnavailable, EmailConflict


class AuthRepository(Protocol):
    def initialize(self): ...
    def find_session(self, token_hash): ...
    def insert_session(self, document): ...
    def rotate_csrf(self, token_hash, csrf_hash, now): ...
    def insert_user(self, document): ...
    def find_user_by_email(self, email): ...
    def find_user_by_id(self, user_id): ...
    def update_user(self, user_id, fields): ...
    def delete_session(self, token_hash): ...
    def failed_logins(self, key, since): ...
    def record_failed_login(self, key, at, expires_at): ...
    def clear_failed_logins(self, key): ...


class UnavailableAuthRepository:
    def _unavailable(self, *args):
        raise AuthUnavailable()

    initialize = find_session = insert_session = rotate_csrf = insert_user = _unavailable
    find_user_by_email = find_user_by_id = update_user = delete_session = _unavailable
    failed_logins = record_failed_login = clear_failed_logins = _unavailable


class MongoAuthRepository:
    def __init__(self, database):
        self.users = database['users']
        self.sessions = database['sessions']
        self.attempts = database['login_attempts']

    def initialize(self):
        try:
            self.users.create_index('email_normalized', unique=True, name='users_email_unique')
            self.sessions.create_index('token_hash', unique=True, name='sessions_token_unique')
            self.sessions.create_index('expires_at', expireAfterSeconds=0, name='sessions_expiry')
            self.attempts.create_index([('key_hash', 1), ('created_at', 1)], name='login_attempts_key')
            self.attempts.create_index('expires_at', expireAfterSeconds=0, name='login_attempts_expiry')
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

    def find_user_by_email(self, email):
        try:
            return self.users.find_one({'email_normalized': email})
        except PyMongoError:
            raise AuthUnavailable() from None

    def find_user_by_id(self, user_id):
        try:
            return self.users.find_one({'_id': user_id})
        except PyMongoError:
            raise AuthUnavailable() from None

    def update_user(self, user_id, fields):
        try:
            return self.users.find_one_and_update(
                {'_id': user_id}, {'$set': fields}, return_document=ReturnDocument.AFTER)
        except PyMongoError:
            raise AuthUnavailable() from None

    def delete_session(self, token_hash):
        try:
            self.sessions.delete_one({'token_hash': token_hash})
        except PyMongoError:
            raise AuthUnavailable() from None

    def failed_logins(self, key, since):
        try:
            cursor = self.attempts.find({'key_hash': key, 'created_at': {'$gt': since}})
            return [item['created_at'] for item in cursor.sort('created_at', 1)]
        except PyMongoError:
            raise AuthUnavailable() from None

    def record_failed_login(self, key, at, expires_at):
        try:
            self.attempts.insert_one({'key_hash': key, 'created_at': at, 'expires_at': expires_at})
        except PyMongoError:
            raise AuthUnavailable() from None

    def clear_failed_logins(self, key):
        try:
            self.attempts.delete_many({'key_hash': key})
        except PyMongoError:
            raise AuthUnavailable() from None
