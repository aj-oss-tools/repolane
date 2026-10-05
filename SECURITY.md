# Security

Repolane is a local tool: no server, no account, and no shared infrastructure between
installs. A vulnerability here almost always means one thing — a way to get the guard
(`scripts/hooks/guard.py`) to allow something it should refuse: a path that escapes the
lane, a chained command that slips past a rule, a way to read a secret file.

## Reporting one

Report it privately through GitHub:
[**Report a vulnerability**](https://github.com/aj-oss-tools/repolane/security/advisories/new)
(the repository's Security tab). Please don't open a public issue for a bypass: every
existing install stays exposed to it until a fix ships, so details are kept private until
then.

Include the kind of command or path shape that gets through and how you ran it. Once a fix
is released, the advisory is published with credit to you unless you'd rather stay
anonymous.

Repolane is maintained on a best-effort basis and provided as is, without warranty, under
the Apache License 2.0.

## What's in scope

The guard's actual behaviour — anything `docs/rules.md` says should be refused, and isn't,
or is refused for the wrong reason. Also in scope: the board (`lane board`) reaching beyond
`127.0.0.1`, making an outbound call, or leaking a secret's contents rather than its key
name — see [the security model page](https://repolane.dev/docs/security/) for what it's
meant to guarantee and what it's a guardrail against rather than a hardened boundary for.

Not in scope: anything that requires an attacker who already has write access to your own
repos or your own machine — that party already has more access than the guard is trying to
withhold from an agent session.
