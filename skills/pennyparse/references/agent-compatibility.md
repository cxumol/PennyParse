# Agent Compatibility

## Portable Contract

This skill intentionally uses the smallest common contract:

- folder name: `pennyparse`
- required file: `SKILL.md`
- required frontmatter: `name` and `description`
- optional lazy files: `references/*.md`
- no required scripts, metadata, or caller-specific tools

Callers that implement the SKILL.md / agentskills.io shape should be able to load the core workflow.

## Install Locations

Use one of these locations depending on the caller:

```text
Claude Code project:     .claude/skills/pennyparse/SKILL.md
Claude Code user:        ~/.claude/skills/pennyparse/SKILL.md
OpenClaw workspace:      <workspace>/skills/pennyparse/SKILL.md
OpenClaw global:         ~/.openclaw/skills/pennyparse/SKILL.md
OpenClaw extra dirs:     skills.load.extraDirs in ~/.openclaw/openclaw.json
Hermes Agent local:      ~/.hermes/skills/pennyparse/SKILL.md
Codex user:              ~/.codex/skills/pennyparse/SKILL.md
Repository copy:         skills/pennyparse/SKILL.md
```

Copy the whole `pennyparse/` folder when the caller supports multi-file skills. If the caller imports only a single `SKILL.md` from a URL, inline any needed reference content into `SKILL.md` before publishing that single file.

## Caller Notes

Claude Code loads skills from project or user skill directories and uses the `description` field to decide when to activate the skill. The `name` field becomes the slash command. Keep frontmatter simple. Configure allowed tools in the caller when needed rather than relying on skill-specific tool policy.

OpenClaw can load workspace skills from `<workspace>/skills/` and global skills from `~/.openclaw/skills/`. Restart or refresh the gateway if a changed skill is not visible.

Hermes Agent stores local skills under `~/.hermes/skills/` and can install or scan external skill sources. Multi-file skills need a folder or repository-style source; direct URL installs are best treated as single-file `SKILL.md` installs.

Codex reads Codex skills from its configured skills directory. It can use `SKILL.md` without extra metadata.

## Portability Checklist

- Keep `SKILL.md` under the common YAML frontmatter shape.
- Keep command examples POSIX shell compatible.
- Resolve reference paths relative to the skill folder.
- Keep secrets in environment variables controlled by the caller.
- Avoid assuming that `allowed-tools` or any platform-only frontmatter field will be honored.

## Source Links

Checked on 2026-05-11:

- Claude Code skills: https://code.claude.com/docs/en/skills
- OpenClaw skills: https://openclawcn.com/en/docs/tools/skills/
- Hermes Agent skills: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md
