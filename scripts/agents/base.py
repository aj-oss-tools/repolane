"""What every agent adapter speaks: the neutral event, tool call and decision, and the base class.

The guard loads this on every tool call, with no bytecode cache, so it stays small and imports only what the guard has
already paid for (no dataclasses, no typing).
"""
import abc
import collections
import enum

namedtuple = collections.namedtuple


class ToolKind(enum.Enum):
    SHELL = "shell"            # runs a command line
    READ = "read"              # one file
    WRITE = "write"            # creates or edits one file
    SEARCH = "search"          # the lines of files under a folder
    LIST = "list"              # file names only
    ENTER_LANE = "enter-lane"  # the agent's own way of moving a session into a folder
    OTHER = "other"
    UNKNOWN = "unknown"        # a tool the adapter only knows by what its arguments name: judged by those paths, then left to the agent's check


class Capability(enum.Enum):
    PRE_COMPACT = "pre-compact"        # an event before the conversation is compacted
    ENTER_LANE = "enter-lane"          # a session can be moved into a lane by name
    STATUS_LINE = "status-line"
    SLASH_COMMANDS = "slash-commands"  # commands and agents installed from templates/
    MEMORY_LINK = "memory-link"        # keeps its memory in a folder of its own, which Repolane links
    RESUME = "resume"                  # a past conversation can be resumed by id
    TOOL_CONTEXT = "tool-context"      # an answer to a tool call can carry context for the model
    SESSION_END = "session-end"        # an event when a session really ends
    RULES_IMPORT = "rules-import"      # its rules file can import REPOLANE.md
    IMPORT_CONVERSATIONS = "import-conversations"   # past conversations are filed by folder, so `lane import` can adopt them
    CONVERSATION_LEDGER = "conversation-ledger"     # conversations are not filed by folder: the hook records which lane each is in


# Event kinds, the words `lane hook` takes. OTHER is an event the guard has nothing to say about.
SESSION_START, PRE_TOOL, POST_TOOL = "session-start", "pre-tool-use", "post-tool-use"
PROMPT, PRE_COMPACT, SESSION_END = "user-prompt-submit", "pre-compact", "session-end"
LANE_ENTER, LANE_LEAVE, OTHER = "worktree-create", "worktree-remove", ""
TURN_END = "turn-end"

# file: what a file tool edits or reads; root: the folder a search or a move is aimed at; target: a name to move to.
# paths: every path the call names, in the order the guard judges them.
ToolCall = namedtuple("ToolCall", "kind name command paths file root pattern glob filetype target",
                      defaults=("", (), "", "", "", "", "", ""))

# malformed: a tool call the guard cannot read, which it refuses. tool is None on a PRE_TOOL event whose fields have the
# wrong type (refused) and on a POST_TOOL event likewise (ignored). session_id and target are as the agent sent them.
Event = namedtuple("Event", "kind cwd session_id tool target malformed extra", defaults=(None, None, None, "", False, None))

# What the agent's process has to do with an answer: print these and exit.
Reply = namedtuple("Reply", "stdout stderr code", defaults=(None, None, 0))

Session = namedtuple("Session", "last id turns first")   # ordered so a sort is newest last, then by id

# Where lib.sh's lane commands put things, for the adapter's installers.
Layout = namedtuple("Layout", "ad product mode repos lanes_dir memory knowledge cache")


class AgentRefusal(Exception):
    """An installer will not do this, and says why in words for the person."""


class Decision(namedtuple("Decision", "kind text context", defaults=("", None))):
    """DENY text=why; ALLOW context=optional; CONTEXT text; REFUSE text (a non-tool event says no);
    ENTER text=the folder a session moves to, context=optional note for the person;
    NONE the guard has no objection and nothing to say, context=True when the owner has pre-approved this call."""
    __slots__ = ()
    DENY, ALLOW, CONTEXT, REFUSE, ENTER, NONE = "deny", "allow", "context", "refuse", "enter", "none"

    @classmethod
    def none(cls, pre_approved=None): return cls(cls.NONE, "", pre_approved)

    @classmethod
    def deny(cls, why): return cls(cls.DENY, why)

    @classmethod
    def allow(cls, context=None): return cls(cls.ALLOW, "", context)

    @classmethod
    def add_context(cls, text): return cls(cls.CONTEXT, text)

    @classmethod
    def refuse(cls, text): return cls(cls.REFUSE, text)

    @classmethod
    def enter(cls, folder, note=None): return cls(cls.ENTER, folder, note)


class AgentAdapter(abc.ABC):
    name = ""
    capabilities = frozenset()
    rules_file = ""    # the file the agent loads its instructions from
    config_dir = ""    # its folder in a project, part of what the plane protects
    resume_hint = ""   # how a person picks a past conversation back up
    launch = ""        # the command that starts a session
    cred_dirs = ()     # folders under the home directory, beyond the shared list, that must never become a reference
    protects_config_at_root = False   # is its config refused to a session at the workspace root as well?
    pre_approved = ()  # commands the guard itself pre-approves; an agent with its own allow-list in settings leaves this empty

    def has(self, capability): return capability in self.capabilities

    def say(self, text):
        """Repolane's text, which is written for Claude Code, in what this agent has."""
        return text

    def rule_matches(self, word, tool):
        """Does a project rule's `tool:` word name this call? The agent's own tool name, or the neutral kind."""
        return word == tool.name or word == tool.kind.value

    def repo_rules_skip(self, path):
        """One of repo_rules' files that is Repolane's own, not the repo's."""
        return False

    def record_session(self, event, lane, cache):
        """A turn started: note which lane this conversation is in, for an agent that does not file them by folder."""

    def check_repo(self, mirror, ref):
        """Why a worktree of this ref cannot be wired for the agent, or None."""
        return None

    def check_folder(self, folder):
        """What is wrong with a session folder's wiring, as sentences."""
        return []

    # ---- the hook protocol: the guard's whole view of the agent. A wrong answer here is a security bug.
    @abc.abstractmethod
    def parse_event(self, raw, hint=None):
        """stdin -> Event, or None when there is nothing to decide. A body that cannot be read but is plainly a tool call
        is a PRE_TOOL event with malformed=True: never None, or the guard would let it through. hint is the event kind when
        the hook command names it (an agent whose body does not)."""

    @abc.abstractmethod
    def claims_pre_tool(self, raw):
        """Does this body, read as text, look like a tool call? What fail-closed rests on when parsing itself blew up."""

    @abc.abstractmethod
    def format_decision(self, event, decision):
        """(event kind, Decision) -> Reply: what the agent has to receive for this answer to count."""

    # ---- what the guard has to know about the agent's files
    @abc.abstractmethod
    def repo_rules(self, root):
        """(instruction files a repo may have, its folder of rule files)."""

    @abc.abstractmethod
    def is_session_config(self, realpath):
        """Is this file the agent's own permission and hook configuration?"""

    @abc.abstractmethod
    def tidy_transcripts(self, session_id, ad, repos):
        """At a session's end: keep its transcript in one place. Returns a line for the log when something moved, else None."""

    # ---- past conversations
    @abc.abstractmethod
    def session_dir(self, folder):
        """Where the transcripts of sessions started in this folder are."""

    @abc.abstractmethod
    def sessions(self, folders):
        """[Session] for sessions started in these folders, newest first."""

    @abc.abstractmethod
    def session_count(self, folder):
        """How many transcripts session_dir(folder) holds."""

    @abc.abstractmethod
    def signature_dir(self, mirror):
        """The folder the board watches to see whether a mirror's sessions changed."""

    @abc.abstractmethod
    def session_owner(self, session_id, repos):
        """The mirror under `repos` a conversation is filed under, or ""."""

    @abc.abstractmethod
    def session_start_input(self, raw):
        """stdin of the session-start hook -> (source, session id, cwd)."""

    @abc.abstractmethod
    def session_start_reply(self, context, screen):
        """What the session-start hook prints: context for the model, screen for the person."""

    # ---- putting the agent's files in place
    @abc.abstractmethod
    def install_workspace(self, product, ad, seed):
        """A new workspace: settings, hooks, rules file. seed(path, text, label) writes a file only if missing, and records
        it. Returns the labels of what else was made."""

    @abc.abstractmethod
    def refresh_workspace(self, product, ad):
        """After an upgrade: bring what install_workspace wrote up to this version, keeping the user's own."""

    @abc.abstractmethod
    def install_lane(self, layout, folder, lane_id, memory):
        """A session folder of a lane (the lane root, or a worktree). Returns the paths under it to keep out of git."""

    @abc.abstractmethod
    def install_lane_rules(self, layout, lane_dir, spec):
        """The rules file at a lane's root."""

    @abc.abstractmethod
    def grant_lane_folders(self, layout):
        """Let each session folder reach the rest of its lane, and the root reach every lane."""
