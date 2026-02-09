from __future__ import annotations

from dataclasses import dataclass

from livekit import api


@dataclass
class TokenResponse:
    token: str
    url: str
    room: str
    identity: str


def create_token(
    *,
    livekit_url: str,
    livekit_api_key: str,
    livekit_api_secret: str,
    room: str,
    identity: str,
    agent_name: str | None = None,
) -> TokenResponse:
    grant = api.VideoGrants(room_join=True, room=room)
    access = api.AccessToken(livekit_api_key, livekit_api_secret).with_identity(identity).with_grants(grant)
    if agent_name:
        access = access.with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=agent_name)],
            )
        )
    token = access.to_jwt()
    return TokenResponse(token=token, url=livekit_url, room=room, identity=identity)
