"""Flask blueprint for OIDC endpoints (discovery, JWKS, refresh, revoke, introspect, userinfo)."""

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar

from flask import Blueprint, Response, jsonify, request

from penguin_aaa.authn.oidc_provider import OIDCProvider
from penguin_aaa.authn.oidc_rp import OIDCRelyingParty

_T = TypeVar("_T")


def _run_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """
    Execute an async coroutine from synchronous Flask handler code.

    Safe both when no event loop is running (the normal Flask/WSGI worker
    case, where a fresh loop is used directly) and when one already is
    (e.g. under pytest-asyncio), in which case the coroutine is run to
    completion on a dedicated background thread to avoid nesting loops.

    Args:
        coro: The coroutine to run to completion.

    Returns:
        The coroutine's result.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def create_oidc_blueprint(provider: OIDCProvider, rp: OIDCRelyingParty) -> Blueprint:
    """
    Create a Flask blueprint with OIDC/OAuth2 endpoints.

    Args:
        provider: The OIDCProvider instance for token operations.
        rp: The OIDCRelyingParty instance for userinfo validation.

    Returns:
        A Flask Blueprint with mounted endpoints.
    """
    bp = Blueprint("penguin_aaa", __name__)

    @bp.route("/.well-known/openid-configuration", methods=["GET"])
    def discovery() -> tuple[Response, int]:
        """Return the OIDC discovery document."""
        return jsonify(provider.discovery_document()), 200

    @bp.route("/.well-known/jwks.json", methods=["GET"])
    def jwks() -> tuple[Response, int]:
        """Return the JWKS for signing keys."""
        resp = jsonify(provider.jwks())
        resp.cache_control.max_age = 3600
        return resp, 200

    @bp.route("/oauth2/token", methods=["POST"])
    def token() -> tuple[Response, int]:
        """Handle token endpoint (refresh token grant, placeholder for auth code)."""
        grant_type = request.form.get("grant_type")

        if grant_type == "refresh_token":
            refresh_token = request.form.get("refresh_token")
            if not refresh_token:
                return jsonify({"error": "refresh_token required"}), 400
            try:
                token_set = provider.refresh(refresh_token)
                return (
                    jsonify(
                        {
                            "access_token": token_set.access_token,
                            "id_token": token_set.id_token,
                            "refresh_token": token_set.refresh_token,
                            "expires_in": token_set.expires_in,
                            "token_type": token_set.token_type,
                        }
                    ),
                    200,
                )
            except ValueError as e:
                return jsonify({"error": "invalid_grant", "error_description": str(e)}), 400
        elif grant_type == "authorization_code":
            return (
                jsonify(
                    {
                        "error": "unsupported_grant_type",
                        "error_description": "auth code exchange not implemented",
                    }
                ),
                501,
            )
        else:
            return jsonify({"error": "unsupported_grant_type"}), 400

    @bp.route("/oauth2/revoke", methods=["POST"])
    def revoke() -> tuple[Response, int]:
        """Handle token revocation (RFC 7009)."""
        token = request.form.get("token")
        token_type_hint = request.form.get("token_type_hint")
        if not token:
            return jsonify({"error": "token required"}), 400
        provider.revoke(token, token_type_hint)
        return jsonify({}), 200

    @bp.route("/oauth2/introspect", methods=["POST"])
    def introspect() -> tuple[Response, int]:
        """Handle token introspection (RFC 7662)."""
        token = request.form.get("token")
        if not token:
            return jsonify({"active": False}), 200
        result = provider.introspect(token)
        return jsonify(result), 200

    @bp.route("/oauth2/userinfo", methods=["GET"])
    def userinfo() -> tuple[Response, int]:
        """Return claims for the authenticated user, verified via the relying party."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "unauthorized"}), 401

        bearer_token = auth_header[len("Bearer ") :]
        try:
            claims = _run_sync(rp.verify_token(bearer_token))
        except Exception as e:
            # Any verification failure (bad signature, expired, wrong issuer/audience,
            # malformed token, oversized token) is treated uniformly as unauthorized.
            return jsonify({"error": "invalid_token", "error_description": str(e)}), 401

        return (
            jsonify(
                {
                    "sub": claims.sub,
                    "iss": claims.iss,
                    "aud": claims.aud,
                    "iat": int(claims.iat.timestamp()),
                    "exp": int(claims.exp.timestamp()),
                    "scope": claims.scope,
                    "roles": claims.roles,
                    "tenant": claims.tenant,
                    "teams": claims.teams,
                }
            ),
            200,
        )

    return bp
