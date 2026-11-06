"""Entry point: wires the voice pipeline and picks which agent answers.

You mostly edit my_agent.py. Come here to change models, silence handling or
turn-taking.

  .env.local
    AGENT_PROFILE = booking | screener | mine     (which agent answers)
    MODEL_PRESET  = budget  | quality             (see models.py)
    AGENT_NAME    = take2-agent                   (must match your dispatch rule)
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    STTContextOptions,
    TurnHandlingOptions,
    UserStateChangedEvent,
    cli,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics

from booking_agent import BookingAgent
from models import load_models
from my_agent import MyAgent
from screener_agent import ScreenerAgent

logger = logging.getLogger("agent")

load_dotenv(".env.local")

AGENTS: dict[str, type[Agent]] = {
    "booking": BookingAgent,
    "screener": ScreenerAgent,
    "mine": MyAgent,
}

AGENT_NAME = os.getenv("AGENT_NAME", "take2-agent")

# Silence: after this many quiet seconds the caller counts as "away".
SILENCE_SECONDS = 20.0
# Check in this many times, then say goodbye and hang up.
MAX_CHECK_INS = 2


def pick_agent() -> Agent:
    profile = os.getenv("AGENT_PROFILE", "mine").strip().lower()
    if profile not in AGENTS:
        raise ValueError(
            f"Unknown AGENT_PROFILE '{profile}'. Choose one of: {', '.join(AGENTS)}"
        )
    return AGENTS[profile]()


def handle_silence(session: AgentSession) -> None:
    """Ask "are you still there?" when the caller goes quiet, then hang up."""
    check_ins = 0
    tasks: set[asyncio.Task[None]] = set()

    async def check_in() -> None:
        nonlocal check_ins
        agent = session.current_agent
        if session.user_state != "away" or session.agent_state != "listening":
            return
        if isinstance(agent, MyAgent) and (agent.state.on_hold or agent.state.result):
            return
        check_ins += 1
        if check_ins <= MAX_CHECK_INS:
            await session.say("Are you still there?")
        else:
            await session.say("I'll let you go. Thanks, goodbye.")
            session.shutdown()

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent) -> None:
        nonlocal check_ins
        if ev.new_state == "speaking":
            check_ins = 0
            for task in tuple(tasks):
                task.cancel()
        elif ev.new_state == "away" and not tasks:
            task = asyncio.create_task(check_in())
            tasks.add(task)
            task.add_done_callback(tasks.discard)

    @session.on("close")
    def _on_close(_event) -> None:
        for task in tuple(tasks):
            task.cancel()


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}
    models = load_models()

    session = AgentSession(
        # Ears: speech-to-text
        stt=models.stt,
        # Bias transcription toward words it would otherwise misspell.
        stt_context_options=STTContextOptions(
            keyterms=["CareCall", "Alex Morgan", "Example Choice PPO"],
            keyterm_detection={"enabled": False},
        ),
        # Brain: the LLM
        llm=models.llm,
        # Voice: text-to-speech
        tts=models.tts,
        expressive=models.expressive,
        # STT owns end-of-turn; room noise must not keep the audio turn open.
        vad=inference.VAD(activation_threshold=0.6, deactivation_threshold=0.45),
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={"mode": "fixed", "min_delay": 0.2, "max_delay": 1.0},
            interruption={
                "enabled": True,
                "mode": "adaptive",
                "min_duration": 0.5,
                "min_words": 1,
                "resume_false_interruption": True,
                "false_interruption_timeout": 1.0,
            },
            preemptive_generation={
                "enabled": True,
                "preemptive_tts": True,
                "max_retries": 2,
            },
        ),
        user_away_timeout=SILENCE_SECONDS,
    )

    handle_silence(session)

    async def log_usage() -> None:
        # Shows model usage per call so you can see what you're spending.
        logger.info("session usage: %s", session.usage)

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=pick_agent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # Removes background noise and other voices before STT hears it.
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
            # Hang up the phone line when the session ends.
            delete_room_on_close=True,
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
