"""One saru session: connections, state, and the turn from text_input to idle.

A turn runs as three stages like speech.SpeechPipeline: the brain's text is cut
into chunks, a producer synthesizes them ahead, and a consumer delivers them to
the stage one at a time. Only stdlib and sibling modules are imported so the
tests need no aiohttp or Claude SDK.
"""

import asyncio
import itertools
import logging

import protocol
import speech
from brain import Done, TextDelta

log = logging.getLogger(__name__)

# speak ids are unique per process, shared by every session.
_speak_ids = itertools.count(1)


class Session:
    def __init__(self, brain, voicevox, ended_grace=2.0):
        self.brain = brain
        self.voicevox = voicevox
        # How long past the wav length a missing speak_ended is waited for.
        self.ended_grace = ended_grace
        self.state = "idle"
        self.connections = []
        self.turn = None
        self.pending = {}  # speak id -> Future resolved by speak_ended

    # connections

    async def add(self, conn):
        self.connections.append(conn)
        await self._send(conn, protocol.state(self.state))

    def remove(self, conn):
        if conn in self.connections:
            self.connections.remove(conn)

    def _stage(self):
        # The most recently added stage wins.
        for conn in reversed(self.connections):
            if conn.role == "stage":
                return conn
        return None

    async def _send(self, conn, message):
        try:
            await conn.send(message)
        except Exception:
            log.exception("send to %s failed, dropping the connection", conn.role)
            self.remove(conn)

    async def _broadcast(self, message):
        for conn in list(self.connections):
            await self._send(conn, message)

    async def _set_state(self, name):
        self.state = name
        await self._broadcast(protocol.state(name))

    # incoming

    async def handle(self, conn, message):
        kind = message["type"]
        if kind == "text_input":
            if self.state != "idle":
                log.info("dropped text_input while %s", self.state)
                return
            # Set before the first await so a second text_input cannot slip in.
            self.state = "thinking"
            self.turn = asyncio.create_task(self._run_turn(message["text"]))
        elif kind == "speak_ended":
            future = self.pending.get(message["id"])
            if future is not None and not future.done():
                future.set_result(None)
        else:
            log.debug("ignored %s", kind)

    async def close(self):
        if self.turn is not None:
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)

    # turn

    async def _run_turn(self, text):
        stage_at_start = self._stage() is not None
        texts, sounds = asyncio.Queue(), asyncio.Queue()
        workers = [
            asyncio.create_task(self._synthesize_all(texts, sounds, stage_at_start)),
            asyncio.create_task(self._deliver_all(sounds)),
        ]
        chunker = speech.Chunker()
        try:
            await self._broadcast(protocol.state("thinking"))
            async for event in self.brain.reply(text):
                if isinstance(event, TextDelta):
                    for chunk in chunker.feed(event.text):
                        texts.put_nowait(chunk)
                elif isinstance(event, Done):
                    break
            for chunk in chunker.flush():
                texts.put_nowait(chunk)
            texts.put_nowait(None)
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn failed")
        finally:
            for worker in workers:
                worker.cancel()
            await self._set_state("idle")

    async def _synthesize_all(self, texts, sounds, enabled):
        while (text := await texts.get()) is not None:
            synthesis = None
            if enabled:
                try:
                    synthesis = await self.voicevox.synthesize(text)
                except (OSError, ValueError) as e:
                    log.warning("VOICEVOX (%s) failed, text only for the rest: %s", self.voicevox.url, e)
                    enabled = False
            sounds.put_nowait((text, synthesis))
        sounds.put_nowait(None)

    async def _deliver_all(self, sounds):
        first = True
        while (item := await sounds.get()) is not None:
            text, synthesis = item
            if first:
                first = False
                await self._set_state("speaking")
            stage = self._stage() if synthesis else None
            if stage is None:
                await self._broadcast(protocol.utterance("saru", text))
                continue
            id = next(_speak_ids)
            future = asyncio.get_running_loop().create_future()
            self.pending[id] = future
            try:
                await self._send(
                    stage,
                    protocol.speak(id, text, synthesis.wav, speech.visemes(synthesis.query)),
                )
                await self._broadcast(protocol.utterance("saru", text))
                if stage not in self.connections:
                    # The send failed and the stage was dropped: nothing to wait for.
                    continue
                timeout =speech.wav_duration(synthesis.wav) + self.ended_grace
                try:
                    await asyncio.wait_for(future, timeout)
                except asyncio.TimeoutError:
                    log.warning("no speak_ended for %d within %.1fs, moving on", id, timeout)
            finally:
                del self.pending[id]
