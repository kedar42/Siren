from __future__ import annotations

from typing import TYPE_CHECKING

from .clear import ClearCommand
from .move import MoveCommand
from .nowplaying import NowPlayingCommand
from .pause import PauseCommand
from .play import PlayCommand
from .queue import QueueCommand
from .remove import RemoveCommand
from .resume import ResumeCommand
from .shuffle import ShuffleCommand
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
        RemoveCommand(bot),
        MoveCommand(bot),
        ClearCommand(bot),
        ShuffleCommand(bot),
        NowPlayingCommand(bot),
    ):
        command.register()
