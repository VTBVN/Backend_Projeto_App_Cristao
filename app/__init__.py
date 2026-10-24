import os
from pathlib import Path

import click
from flask import Blueprint, Flask, jsonify, request
from pymongo import MongoClient
from werkzeug.exceptions import HTTPException

from app.bible import BibleService
from app.cache import MongoCache, SQLiteCache
from app.errors import ApiError, CacheUnavailable, AuthUnavailable
from app.auth import auth, configure_auth
from app.auth_repository import MongoAuthRepository, UnavailableAuthRepository


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True, static_folder=None)
    app.config.from_mapping(
        APP_ENV=os.getenv("APP_ENV", "development"),
        APP_ORIGIN=os.getenv("APP_ORIGIN", "http://localhost:5173"),
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
        ANONYMOUS_SESSION_TTL_SECONDS=int(os.getenv("ANONYMOUS_SESSION_TTL_SECONDS", "1800")),
        SESSION_TTL_SECONDS=int(os.getenv("SESSION_TTL_SECONDS", "43200")),
        MONGODB_URI=os.getenv("MONGODB_URI", ""),
        MONGODB_DATABASE=os.getenv("MONGODB_DATABASE", "app_cristao_dev"),
        BIBLE_API_BASE_URL=os.getenv("BIBLE_API_BASE_URL", "https://bible-api.com"),
        BIBLE_CONNECT_TIMEOUT_SECONDS=float(os.getenv("BIBLE_CONNECT_TIMEOUT_SECONDS", "2")),
        BIBLE_READ_TIMEOUT_SECONDS=float(os.getenv("BIBLE_READ_TIMEOUT_SECONDS", "5")),
        BIBLE_CACHE_TTL_SECONDS=int(os.getenv("BIBLE_CACHE_TTL_SECONDS", "86400")),
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_REQUEST_BYTES", "53477376")),
        CACHE_SQLITE_PATH=str(Path(app.instance_path) / "bible-cache.sqlite3"),
    )
    if config:
        app.config.update(config)
    if app.config["BIBLE_API_BASE_URL"] != "https://bible-api.com":
        raise ValueError("BIBLE_API_BASE_URL deve ser https://bible-api.com.")
    for key in ("BIBLE_CONNECT_TIMEOUT_SECONDS", "BIBLE_READ_TIMEOUT_SECONDS", "BIBLE_CACHE_TTL_SECONDS"):
        if not 0 < app.config[key] <= 86400:
            raise ValueError(f"Configuração inválida: {key}.")
    if app.config["APP_ENV"] not in ("development", "production", "testing"):
        raise ValueError("APP_ENV inválido.")
    configure_auth(app)
    mongo = None
    if app.config["MONGODB_URI"]:
        mongo = MongoClient(app.config["MONGODB_URI"], serverSelectionTimeoutMS=2000,
                            connectTimeoutMS=2000, socketTimeoutMS=2000, tz_aware=True)
        app.extensions["mongo"] = mongo
    repository = app.config.get("AUTH_REPOSITORY")
    if repository is None:
        repository = (MongoAuthRepository(mongo[app.config["MONGODB_DATABASE"]])
                      if mongo is not None else UnavailableAuthRepository())
    app.extensions["auth_repository"] = repository
    app.register_blueprint(auth)
    cache = app.config.get("BIBLE_CACHE")
    if cache is None:
        if app.config["MONGODB_URI"]:
            cache = MongoCache(mongo[app.config["MONGODB_DATABASE"]]["bible_cache"])
        elif app.config["APP_ENV"] == "production":
            raise ValueError("Produção exige MONGODB_URI; não há fallback para SQLite.")
        else:
            cache = SQLiteCache(app.config["CACHE_SQLITE_PATH"])
    app.extensions["bible_cache"] = cache
    app.extensions["bible_service"] = BibleService(cache, app.config)
    api = Blueprint("api", __name__, url_prefix="/api")

    @api.get("/health")
    def health():
        return jsonify(data={"status": "ok"})

    @api.get("/bible/passages")
    def passages():
        if any(k not in ("reference", "translation") or len(request.args.getlist(k)) != 1
               for k in request.args):
            raise ApiError(400, "validation_error", "Parâmetros inválidos.")
        return jsonify(data=app.extensions["bible_service"].passage(
            request.args.get("reference"), request.args.get("translation", "almeida")
        ))

    app.register_blueprint(api)

    @app.errorhandler(ApiError)
    def api_error(error):
        response = jsonify(error={"code": error.code, "message": error.message})
        response.status_code = error.status
        if error.retry_after is not None:
            response.headers["Retry-After"] = str(error.retry_after)
        return response

    @app.errorhandler(AuthUnavailable)
    def auth_unavailable(error):
        return jsonify(error={"code": "auth_unavailable", "message": "Cadastro indisponível."}), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        response = error.get_response()
        response.data = app.json.dumps({"error": {"code": "http_error", "message": error.name}})
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.error("Erro interno não tratado (%s).", type(error).__name__)
        return jsonify(error={"code": "internal_error", "message": "Erro interno."}), 500

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.cli.command("init-cache")
    def init_cache():
        """Verify cache connectivity and initialize indexes explicitly."""
        try:
            cache.initialize()
        except CacheUnavailable:
            raise click.ClickException("Cache indisponível; confira a configuração e a rede.") from None
        click.echo(f"Cache inicializado: {type(cache).__name__}.")

    @app.cli.command("init-auth")
    def init_auth():
        """Initialize account and session indexes explicitly."""
        try:
            repository.initialize()
        except AuthUnavailable:
            raise click.ClickException("Autenticação indisponível; confira configuração e rede.") from None
        click.echo("Índices de usuários e sessões inicializados.")

    return app
