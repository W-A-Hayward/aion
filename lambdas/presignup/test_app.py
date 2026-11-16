import importlib.util
import os

import pytest

_spec = importlib.util.spec_from_file_location("presignup_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


def event(username):
    return {"userName": username, "request": {"userAttributes": {}}, "response": {}}


@pytest.mark.parametrize("name", ["robin", "Robin_T", "a.b-c", "x" * 32])
def test_valid_usernames_are_confirmed_without_verifying_anything(name):
    out = app.lambda_handler(event(name), None)
    assert out["response"] == {"autoConfirmUser": True, "autoVerifyEmail": False, "autoVerifyPhone": False}


@pytest.mark.parametrize("name", ["ab", "x" * 33, "has space", "émile", "<script>", ""])
def test_invalid_usernames_are_refused(name):
    with pytest.raises(Exception, match="Usernames are 3-32 characters"):
        app.lambda_handler(event(name), None)
