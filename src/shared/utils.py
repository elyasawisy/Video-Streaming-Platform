"""Utility helpers shared across services."""

from flask import jsonify

def json_response(payload: dict, status: int = 200):
    """Return a JSON response with given status."""
    return jsonify(payload), status

