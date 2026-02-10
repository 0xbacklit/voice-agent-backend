from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, JobContext, room_io
from livekit.plugins import bey, cartesia, deepgram, noise_cancellation, openai, silero

from app.agents.voice_agent import VoiceBookingAgent
from app.config import settings

load_dotenv()

def _start_health_server() -> None:
    port = os.getenv("PORT")
    if not port:
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):  # noqa: A002
            return

    server = HTTPServer(("0.0.0.0", int(port)), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


def build_session() -> AgentSession:
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    elif settings.openrouter_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openrouter_api_key)
    if settings.openai_api_base:
        os.environ.setdefault("OPENAI_API_BASE", settings.openai_api_base)
    if settings.bey_api_key:
        os.environ.setdefault("BEY_API_KEY", settings.bey_api_key)
    return AgentSession(
        stt=deepgram.STT(model="nova-2"),
        llm=openai.LLM(
            model=settings.openrouter_model,
            base_url=settings.openai_api_base,
            api_key=settings.openai_api_key or settings.openrouter_api_key,
            temperature=0.3,
        ),
        tts=cartesia.TTS(model="sonic-3", voice=os.getenv("CARTESIA_VOICE_ID", "")),
        vad=silero.VAD.load(),
    )


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    session = build_session()
    session.userdata = {"session_id": ctx.room.name}
    avatar_id = settings.bey_avatar_id or os.getenv("BEY_AVATAR_ID")
    if settings.bey_enabled and avatar_id:
        avatar = bey.AvatarSession(avatar_id=avatar_id)
        await avatar.start(room=ctx.room, agent_session=session)
    await session.start(
        room=ctx.room,
        agent=VoiceBookingAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(),
        ),
    )
    session.say(settings.agent_greeting, allow_interruptions=False)


if __name__ == "__main__":
    _start_health_server()
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=settings.livekit_agent_name,
        )
    )
