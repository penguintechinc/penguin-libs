# penguin-libs Migration Guide

## Migrating to 0.2.0

No breaking changes. The 0.2.0 release adds the `penguin_libs.flask` submodule.

### Adopting Flask Helpers

Install the Flask extra:

```bash
pip install penguin-libs[flask]
```

If your Flask app uses custom response helpers, migrate to the standard envelope:

**Before:**
```python
from flask import jsonify

@app.route("/api/v1/users")
def list_users():
    users = get_users()
    return jsonify({"status": "success", "data": users}), 200

@app.route("/api/v1/users/<int:user_id>")
def get_user(user_id):
    user = find_user(user_id)
    if not user:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "success", "data": user}), 200
```

**After:**
```python
from penguin_libs.flask import success_response, error_response, paginate, get_pagination_params

@app.route("/api/v1/users")
def list_users():
    page, per_page = get_pagination_params()
    users = get_users()
    data = paginate(users, page, per_page)
    return success_response(data=data["items"], meta=data)

@app.route("/api/v1/users/<int:user_id>")
def get_user(user_id):
    user = find_user(user_id)
    if not user:
        return error_response("User not found", status_code=404)
    return success_response(data=user)
```

### Response Envelope Format

The standard envelope uses:
```json
{"status": "success", "data": ..., "message": "Success", "meta": {...}}
{"status": "error", "message": "User not found"}
```

Clients should check `status` rather than HTTP status codes for application-level success/failure.
