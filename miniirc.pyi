# miniirc stub file
# This allows type checking without breaking compatibility or making the main
#   file slower to load.

import io, ssl
from re import Match
from collections.abc import Callable, Iterable
from typing import Any, Optional, Union, overload, NamedTuple
from asyncio import AbstractEventLoop

# The version string and tuple
ver: tuple[int, int, int, str] = ...
version: str = ...
__version__: str = ...

# __all__ and _default_caps
__all__: list[str] = ['Handler', 'IRC', 'IRCMessage', 'Hostmask', 'register_numerics', 'HandlersCollection']
_default_caps: set[str] = {
    'account-notify',
    'account-tag',
    'away-notify',
    'cap-notify',
    'chghost',
    'extended-join',
    'invite-notify',
    'message-tags',
    'server-time',
    'sts',
}

# Get the certificate list.
get_ca_certs: Callable[[], Optional[str]]
try:
    from certifi import where as get_ca_certs  # type: ignore
except ImportError:
    def get_ca_certs():
        pass

_handler_func_1 = Callable[['IRC'], Any]
_handler_func_2 = Callable[['IRC', 'IRCMessage'], Any]

class Handler:
    """Internal handler wrapper for IRC event callbacks."""
    func: Any
    awaitable: bool
    params_count: int
    def __init__(self, func: Callable) -> None: ...

class HandlersCollection:
    """Handler decorator and manager for IRC events."""
    handlers: dict[str, list[Handler]]
    def __init__(self) -> None: ...
    def __call__(self, *events: str) -> Callable[[Any], Any]: ...
    def getHandlers(self) -> dict[str, list[Handler]]: ...

handle: HandlersCollection

@overload
def handle(*events: str) -> Callable[[_handler_func_1], _handler_func_1]: ...
@overload
def handle(*events: str) -> Callable[[_handler_func_2], _handler_func_2]: ...

# Parse IRCv3 tags (renamed to match implementation)
_ircv3_tag_escapes: dict[str, str] = {':': ';', 's': ' ', 'r': '\r', 'n': '\n'}

def _unescape_tag(match: Match) -> str: ...
def _tag_list_to_dict(tag_list: Iterable[str]) -> dict[str, str]: ...

# Create the IRCv2/3 parser
class Hostmask(NamedTuple):
    nick: str = ''
    user: str = ''
    host: str = ''

class IRCMessage(NamedTuple):
    command: str
    hostmask: Hostmask = Hostmask()
    tags: dict | None = None
    args: list | None = None

    def sub_command(self, prefix: str) -> "IRCMessage | None": ...
    def handle(self, irc: "IRC") -> bool: ...
    async def _start_handler(self, handler: Any, irc: "IRC") -> None: ...

# Escape tags
def _escape_tag(tag: str) -> str: ...

# Convert a dict into an IRCv3 tags string
def _dict_to_tags(tags: dict[str, Union[str, bool]]) -> bytes: ...
def register_numerics(numerics: dict[str, str]) -> None: ...
def _event_name_to_numeric(event: str) -> str | None: ...

# Create the IRC class
class IRC:
    connected: Optional[bool] = None
    msglen: int = 512

    host: str
    port: int
    nick: str
    current_nick: str
    channels: set[str]
    username: str
    realname: str
    password: Optional[str]
    ssl: Optional[bool]
    persist: bool
    ircv3_caps: set[str]
    active_caps: set[str]
    isupport: dict[str, Union[str, int]]
    connect_modes: Optional[str]
    quit_message: str
    ping_interval: int
    ping_timeout: Optional[int]
    verify_ssl: bool
    server_password: Optional[str]
    max_reconnect_attempts: int

    # Internal runtime attrs
    _sendq: Optional[list[Any]]
    _loop: AbstractEventLoop
    _task: Optional[Any]
    _sasl: bool
    _unhandled_caps: Optional[dict[str, Any]]
    _combined_handlers: Optional[dict[str, list[Any]]]
    _nickname_re: Any
    _msg_re: Any

    handle: HandlersCollection

    async def quote(
        self, *msg: str, force: bool = False, tags: Optional[dict[str, Union[str, bool]]] = None
    ) -> None: ...
    async def send(
        self, *msg: str, force: bool = False, tags: Optional[dict[str, Union[str, bool]]] = None
    ) -> None: ...
    async def command(
        self, command: str, *args: str, force: bool = False, tags: Optional[dict[str, Union[str, bool]]] = None
    ) -> None: ...
    async def msg(self, target: str, msg: str, tags: Optional[dict[str, Union[str, bool]]] = None) -> None: ...
    async def notice(self, target: str, msg: str, tags: Optional[dict[str, Union[str, bool]]] = None) -> None: ...
    async def ctcp(
        self, target: str, *msg: str, reply: bool = False, tags: Optional[dict[str, Union[str, bool]]] = None
    ) -> None: ...
    async def me(self, target: str, msg: str, tags: Optional[dict[str, Union[str, bool]]] = None) -> None: ...

    @overload
    def Handler(*events: str) -> Callable[[_handler_func_1], _handler_func_1]: ...
    @overload
    def Handler(*events: str) -> Callable[[_handler_func_2], _handler_func_2]: ...

    async def connect(self, *, loop: Optional[Any] = None) -> None: ...

    def _create_ssl_context(self) -> ssl.SSLContext: ...
    async def _establish_connection(self, ctx: ssl.SSLContext) -> None: ...
    async def _process_line(self, line: str) -> None: ...
    def debug_print_line(self, line: str) -> None: ...
    async def disconnect(self, msg: Optional[str] = None, *, auto_reconnect: bool = False) -> None: ...
    async def finish_negotiation(self, cap: str) -> None: ...
    def message_parser(self, msg: str) -> IRCMessage | None: ...
    def get_combined_handlers(self) -> dict[str, list[Any]]: ...
    async def wait_until_disconnected(self) -> None: ...
    def on_disconnect(self) -> None: ...
    def alter_nickname(self) -> str: ...

    # Initialize the class
    def __init__(
        self,
        host: str,
        port: int,
        nick: str,
        *,
        channels: Optional[Union[Iterable[str], str]] = None,
        username: Optional[str] = None,
        realname: Optional[str] = None,
        password: Optional[str] = None,
        server_password: Optional[str] = None,
        persist: bool = True,
        ssl: Optional[Union[bool, ssl.SSLContext]] = None,
        verify_ssl: bool = True,
        ircv3_caps: Optional[set[str]] = None,
        connect_modes: Optional[str] = None,
        ping_interval: int = 60,
        ping_timeout: Optional[int] = None,
        max_reconnect_attempts: int = 10
    ) -> None: ...
