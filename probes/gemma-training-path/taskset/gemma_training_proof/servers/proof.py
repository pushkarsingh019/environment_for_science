"""Shared stateful MCP tool for the disposable training-path proof."""

import verifiers.v1 as vf
from pydantic import Field

ROUTES = ("amber", "blue", "green", "violet")


class ProofState(vf.State):
    route_tokens: dict[str, str] = Field(default_factory=dict)
    chosen_route: str | None = None
    returned_token: str | None = None
    calls: int = 0


class ProofToolset(vf.Toolset[vf.SharedToolsetConfig, ProofState]):
    TOOL_PREFIX = "proof"

    @vf.tool
    async def choose_route(self, route: str) -> str:
        """Choose one named route and return its opaque token."""
        if route not in self.state.route_tokens:
            return f"error: route must be one of {', '.join(ROUTES)}"
        self.state.calls += 1
        self.state.chosen_route = route
        self.state.returned_token = self.state.route_tokens[route]
        return self.state.returned_token


if __name__ == "__main__":
    ProofToolset.run()
