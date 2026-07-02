from pathlib import Path

import pytest

from servicedoc.proto.parser import ProtoFileParser


@pytest.fixture
def proto_fixture() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "sample_go" / "service.proto"


def test_services_parsed(proto_fixture):
    parser = ProtoFileParser()
    services, messages = parser.parse(proto_fixture)
    assert len(services) == 1
    assert services[0].name == "UserService"


def test_methods_parsed(proto_fixture):
    parser = ProtoFileParser()
    services, _ = parser.parse(proto_fixture)
    method_names = {m.name for m in services[0].methods}
    assert "GetUser" in method_names
    assert "CreateUser" in method_names
    assert "DeleteUser" in method_names
    assert "ListUsers" in method_names


def test_streaming_detected(proto_fixture):
    parser = ProtoFileParser()
    services, _ = parser.parse(proto_fixture)
    list_users = next(m for m in services[0].methods if m.name == "ListUsers")
    assert list_users.server_streaming is True
    assert list_users.client_streaming is False


def test_messages_parsed(proto_fixture):
    parser = ProtoFileParser()
    _, messages = parser.parse(proto_fixture)
    msg_names = {m.name for m in messages}
    assert "GetUserRequest" in msg_names
    assert "UserResponse" in msg_names


def test_message_fields(proto_fixture):
    parser = ProtoFileParser()
    _, messages = parser.parse(proto_fixture)
    create_req = next(m for m in messages if m.name == "CreateUserRequest")
    field_names = {f.name for f in create_req.fields}
    assert "username" in field_names
    assert "email" in field_names
    assert "role" in field_names
