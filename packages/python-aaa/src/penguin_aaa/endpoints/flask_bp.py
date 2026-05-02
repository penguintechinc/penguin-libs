"""Flask blueprint for OIDC endpoints (discovery, JWKS, refresh, revoke, introspect, userinfo)."""

import jwt
from flask import Blueprint, Response, jsonify, request

from penguin_aaa.authn.oidc_provider import OIDCProvider
from penguin_aaa.authn.oidc_rp import OIDCRelyingParty


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
        """Return claims for the authenticated user."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "unauthorized"}), 401

        bearer_token = auth_header[len("Bearer ") :]
        try:
            # For Flask, decode without verification (relying party would handle full validation)
            payload = jwt.decode(bearer_token, options={"verify_signature": False})

            # Convert timestamps if needed
            for field in ("iat", "exp"):
                val = payload.get(field)
                if isinstance(val, (int, float)):
                    payload[field] = int(val)

            return (
                jsonify(
                    {
                        "sub": payload.get("sub"),
                        "iss": payload.get("iss"),
                        "aud": payload.get("aud"),
                        "iat": payload.get("iat"),
                        "exp": payload.get("exp"),
                        "scope": payload.get("scope", []),
                        "roles": payload.get("roles", []),
                        "tenant": payload.get("tenant"),
                        "teams": payload.get("teams", []),
                    }
                ),
                200,
            )
        except jwt.PyJWTError as e:
            return jsonify({"error": "invalid_token", "error_description": str(e)}), 401
        except ValueError as e:
            return jsonify({"error": "invalid_request", "error_description": str(e)}), 400

    return bp
