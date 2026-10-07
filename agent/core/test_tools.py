import pytest

import brain
import tools


async def nothing(args):
    return ""


def test_registry_has_only_dance():
    registry = tools.registry(dance=nothing)
    assert [tool.name for tool in registry] == ["dance"]
    assert registry[0].handler is nothing
    assert registry[0].input_schema["type"] == "object"


def test_claude_options_allow_only_dance_and_no_builtin_tools():
    fields = brain.option_fields("sonnet", tools.registry(dance=nothing))
    assert fields["allowed_tools"] == ["mcp__saru__dance"]
    assert fields["tools"] == []
    assert fields["strict_mcp_config"] is True
    assert fields["env"] == brain.ISOLATION_ENV


def test_claude_options_carry_the_registry_as_an_mcp_server():
    pytest.importorskip("claude_agent_sdk")
    options = brain.build_options("sonnet", tools.registry(dance=nothing))
    assert list(options.mcp_servers) == ["saru"]
    assert options.allowed_tools == ["mcp__saru__dance"]
    assert options.tools == []
