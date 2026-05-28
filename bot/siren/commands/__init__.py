from __future__ import annotations

from typing import TYPE_CHECKING

from .pause import PauseCommand
from .play import PlayCommand
from .queue import QueueCommand
from .resume import ResumeCommand
from .skip import SkipCommand
from .stop import StopCommand

if TYPE_CHECKING:
    from ..bot import SirenBot


def register_commands(bot: "SirenBot") -> None:
    for command in (
        PlayCommand(bot),
        SkipCommand(bot),
        StopCommand(bot),
        PauseCommand(bot),
        ResumeCommand(bot),
        QueueCommand(bot),
    ):
        command.register()
