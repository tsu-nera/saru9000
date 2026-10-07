"""One saru session: connections, state, and the turn from text_input to idle.

With a listener (listen.py) the session is half duplex: hearing a sentence
pauses the listener, and it resumes once the turn is over, i.e. after the
last speak_ended (or its timeout), or after the text-only reply.

A turn runs as three stages: the brain's text is cut
into chunks, a producer synthesizes them ahead, and a consumer delivers them to
the stage one at a time. Expression tags in the text ("[happy]") are taken
out before chunking and ride on the speak of the chunk after them; the face
goes back to neutral after the last speak_ended. When the brain used the dance
tool, the stage dances after that and the turn (still speaking, listener still
paused) lasts until motion_ended. Only stdlib and sibling
modules are imported so the tests need no aiohttp or Claude SDK.
"""

import asyncio
import itertools
import logging

import expression
import listen
import protocol
import speech
from brain import Done, TextDelta

log = logging.getLogger(__name__)

# speak ids are unique per process, shared by every session.
_speak_ids = itertools.count(1)

# The dance is about 100 s; a stage that never answers frees the turn after this.
MOTION_TIMEOUT = 180.0


class Session:
    def __init__(self, brain, voicevox, name="agent", ended_grace=2.0, motion_timeout=MOTION_TIMEOUT):
        self.brain = brain
        self.name = name  # the character, shown next to its utterances
        self.voicevox = voicevox
        # How long past the wav length a missing speak_ended is waited for.
        self.ended_grace = ended_grace
        self.motion_timeout = motion_timeout
        self.state = "idle"
        self.connections = []
        self.turn = None
        self.pending = {}  # speak id -> Future resolved by speak_ended
        self.motions = {}  # motion name -> Future resolved by motion_ended
        self.dance_requested = False  # set by the dance tool during a turn
        self.listener = None  # listen.Listener while hearing the user
        # Set by the first ready from a stage; --audio-in waits for it.
        self.stage_ready = asyncio.Event()

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

    def _resting(self):
        return "listening" if self.listener is not None else "idle"

    # hearing

    async def listen(self, listener, blocks, one_at_a_time=False):
        """Hear the user from blocks until they run out, then stop listening.

        one_at_a_time waits for each turn before reading on: wav files are
        read faster than real time, and their audio would otherwise be
        dropped by the paused listener. The microphone must keep being read.
        """
        self.listener = listener
        if self.state == "idle":
            await self._set_state("listening")
        try:
            async for text in listen.utterances(listener, blocks):
                await self.hear(text)
                if one_at_a_time:
                    await self.wait_turn()
            await self.wait_turn()
        finally:
            self.listener = None
            if self.state == "listening":
                await self._set_state("idle")

    async def hear(self, text):
        """A sentence the listener recognized: answer it like a text_input."""
        if self.state != "listening":
            log.info("dropped heard %r while %s", text, self.state)
            return
        self._start_turn(text, heard=True)

    async def wait_turn(self):
        if self.turn is not None:
            await asyncio.gather(self.turn, return_exceptions=True)

    def _start_turn(self, text, heard=False):
        # Set before the first await so a second input cannot slip in.
        self.state = "thinking"
        self.dance_requested = False
        if self.listener is not None:
            self.listener.pause()
        self.turn = asyncio.create_task(self._run_turn(text, heard))

    # incoming

    async def handle(self, conn, message):
        kind = message["type"]
        if kind == "text_input":
            if self.state not in ("idle", "listening"):
                log.info("dropped text_input while %s", self.state)
                return
            self._start_turn(message["text"])
        elif kind == "ready":
            if conn.role == "stage":
                self.stage_ready.set()
        elif kind == "speak_ended":
            future = self.pending.get(message["id"])
            if future is not None and not future.done():
                future.set_result(None)
        elif kind == "motion_ended":
            future = self.motions.get(message["name"])
            if future is not None and not future.done():
                future.set_result(None)
        else:
            log.debug("ignored %s", kind)

    # tools

    async def dance(self, args):
        """Handler of the dance tool: the dance starts once the reply is spoken."""
        if self._stage() is None:
            return "今は舞台がつながっていないので踊れない。そのことを短く伝えて。"
        self.dance_requested = True
        log.info("dance requested")
        return "返事を読み上げ終わったら踊り始める。これから踊ることを一言だけ伝えて。"

    async def close(self):
        if self.turn is not None:
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)

    # turn

    async def _run_turn(self, text, heard=False):
        stage_at_start = self._stage() is not None
        texts, sounds = asyncio.Queue(), asyncio.Queue()
        workers = [
            asyncio.create_task(self._synthesize_all(texts, sounds, stage_at_start)),
            asyncio.create_task(self._deliver_all(sounds)),
        ]
        extractor = expression.Extractor()
        chunker = speech.Chunker()
        face = None  # the last tag, until a chunk starts after it

        def put(parts):
            nonlocal face
            for part in parts:
                if isinstance(part, expression.Tag):
                    face = part.name
                    continue
                for chunk in chunker.feed(part):
                    texts.put_nowait((chunk, face))
                    face = None

        try:
            if heard:
                await self._broadcast(protocol.utterance("user", text))
            await self._broadcast(protocol.state("thinking"))
            async for event in self.brain.reply(text):
                if isinstance(event, TextDelta):
                    put(extractor.feed(event.text))
                elif isinstance(event, Done):
                    break
            put(extractor.flush())
            for chunk in chunker.flush():
                texts.put_nowait((chunk, face))
            texts.put_nowait(None)
            await asyncio.gather(*workers)
            if self.dance_requested:
                await self._play_motion("dance")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn failed")
        finally:
            self.dance_requested = False
            for worker in workers:
                worker.cancel()
            if self.listener is not None:
                self.listener.resume()
            await self._set_state(self._resting())

    async def _synthesize_all(self, texts, sounds, enabled):
        while (item := await texts.get()) is not None:
            text, face = item
            synthesis = None
            if enabled:
                try:
                    synthesis = await self.voicevox.synthesize(text)
                except (OSError, ValueError) as e:
                    log.warning("VOICEVOX (%s) failed, text only for the rest: %s", self.voicevox.url, e)
                    enabled = False
            sounds.put_nowait((text, face, synthesis))
        sounds.put_nowait(None)

    async def _deliver_all(self, sounds):
        first = True
        faced = False  # the stage was told a face or a speak this turn
        while (item := await sounds.get()) is not None:
            text, face, synthesis = item
            if first:
                first = False
                await self._set_state("speaking")
            stage = self._stage() if synthesis else None
            if stage is None:
                if face is not None and (fallback := self._stage()) is not None:
                    # Unspoken text still changes the face.
                    await self._send(fallback, protocol.expression(face))
                    faced = True
                await self._broadcast(protocol.utterance("agent", text, self.name))
                continue
            faced = True
            id = next(_speak_ids)
            future = asyncio.get_running_loop().create_future()
            self.pending[id] = future
            try:
                await self._send(
                    stage,
                    protocol.speak(id, text, synthesis.wav, speech.visemes(synthesis.query), face),
                )
                await self._broadcast(protocol.utterance("agent", text, self.name))
                if stage not in self.connections:
                    # The send failed and the stage was dropped: nothing to wait for.
                    continue
                timeout = speech.wav_duration(synthesis.wav) + self.ended_grace
                try:
                    await asyncio.wait_for(future, timeout)
                except asyncio.TimeoutError:
                    log.warning("no speak_ended for %d within %.1fs, moving on", id, timeout)
            finally:
                del self.pending[id]
        stage = self._stage()
        if faced and stage is not None:
            await self._send(stage, protocol.expression("neutral"))

    async def _play_motion(self, name):
        stage = self._stage()
        if stage is None:
            log.info("no stage, skipped motion %s", name)
            return
        if self.state != "speaking":
            await self._set_state("speaking")
        future = asyncio.get_running_loop().create_future()
        self.motions[name] = future
        try:
            await self._send(stage, protocol.motion(name))
            if stage not in self.connections:
                return
            try:
                await asyncio.wait_for(future, self.motion_timeout)
            except asyncio.TimeoutError:
                log.warning("no motion_ended for %s within %.0fs, moving on", name, self.motion_timeout)
        finally:
            del self.motions[name]
