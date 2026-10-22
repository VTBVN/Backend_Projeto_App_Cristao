from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pymongo.errors import DuplicateKeyError, OperationFailure, ServerSelectionTimeoutError

from app.auth_repository import MongoAuthRepository
from app.errors import AuthUnavailable, EmailConflict


@pytest.fixture
def repository():
    database = {"users": MagicMock(), "sessions": MagicMock()}
    return MongoAuthRepository(database)


def test_indexes(repository):
    repository.initialize()
    repository.users.create_index.assert_called_once_with('email_normalized', unique=True, name='users_email_unique')
    assert repository.sessions.create_index.call_count == 2
    repository.sessions.create_index.assert_any_call('token_hash', unique=True, name='sessions_token_unique')
    repository.sessions.create_index.assert_any_call('expires_at', expireAfterSeconds=0, name='sessions_expiry')


def test_session_queries_and_rotation(repository):
    at = datetime.now(timezone.utc)
    repository.find_session('hashed')
    repository.sessions.find_one.assert_called_once_with({'token_hash': 'hashed'})
    repository.sessions.update_one.return_value.matched_count = 1
    assert repository.rotate_csrf('hashed', 'csrf-hash', at)
    repository.sessions.update_one.assert_called_once_with(
        {'token_hash': 'hashed', 'expires_at': {'$gt': at}}, {'$set': {'csrf_hash': 'csrf-hash'}})
    repository.sessions.update_one.return_value.matched_count = 0
    assert not repository.rotate_csrf('hashed', 'csrf-hash', at)
    document = {'token_hash': 'hashed'}
    repository.insert_session(document)
    repository.sessions.insert_one.assert_called_once_with(document)


def test_atomic_insert_and_duplicate(repository):
    user = {'email_normalized': 'a@example.com'}
    assert repository.insert_user(user) == user
    repository.users.insert_one.assert_called_once_with(user)
    repository.users.insert_one.side_effect = DuplicateKeyError('duplicate')
    with pytest.raises(EmailConflict):
        repository.insert_user(user)
    repository.users.find_one.assert_not_called()


@pytest.mark.parametrize('method, collection, operation, args', [
    ('initialize', 'users', 'create_index', ()),
    ('find_session', 'sessions', 'find_one', ('hash',)),
    ('insert_session', 'sessions', 'insert_one', ({},)),
    ('rotate_csrf', 'sessions', 'update_one', ('hash', 'csrf', datetime.now(timezone.utc))),
    ('insert_user', 'users', 'insert_one', ({},))])
@pytest.mark.parametrize('error', [ServerSelectionTimeoutError('private uri'), OperationFailure('private')])
def test_mongo_errors_controlled(repository, method, collection, operation, args, error):
    getattr(getattr(repository, collection), operation).side_effect = error
    with pytest.raises(AuthUnavailable):
        getattr(repository, method)(*args)
