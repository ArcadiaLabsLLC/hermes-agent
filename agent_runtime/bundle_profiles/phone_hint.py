"""The phone agent's platform hint, derived from the phone profile's disabled toolsets.

Owner ruling 2026-09-28 (plan Stage 5, "Agents know they are on a phone"): a
phone agent is told it has no shell, no terminal, no file system beyond its
sandbox and no background processes, so it does not plan work it cannot do —
missing tools alone are not enough, the model would still hand the user shell
steps to run — and it says when a task needs the desktop.

The text is not written by hand: each capability below names the toolsets that
provide it, and the capability is listed as ABSENT exactly when the profile
manifest disables every one of them. Turn a toolset back on in
``bundled-phone.yaml`` and its sentence leaves the hint with no edit here.
Upstream's per-platform table (``agent.prompt_builder.PLATFORM_HINTS``) carries
the result under the ``phone`` key, put there by :func:`install_phone_platform_hint` —
which the phone's entry (the embedded serve) calls — so ``prompt_builder.py`` keeps
upstream's bytes (lane h11-fp, 2026-09-29).
"""

from __future__ import annotations

from agent_runtime.bundle_profiles.manifest import ProfileManifest, load_profile

__layer__ = "policy"

__all__ = ["CAPABILITIES", "PHONE_PROFILE", "absent_capabilities", "install_phone_platform_hint", "phone_platform_hint"]

PHONE_PROFILE = "bundled-phone"

#: (the toolsets that provide a capability, the phrase naming its absence).
CAPABILITIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("terminal",), "no shell or terminal"),
    (("terminal", "cronjob"), "no background processes or scheduled jobs"),
    (("code_execution",), "no code execution"),
    (("file",), "no file system beyond this app's own sandbox"),
    (("browser", "browser-cdp", "browser-use", "computer_use"), "no browser or desktop automation"),
)


def absent_capabilities(manifest: ProfileManifest) -> list[str]:
    disabled = set(manifest.disabled_toolsets)
    return [phrase for toolsets, phrase in CAPABILITIES if disabled.issuperset(toolsets)]


def _joined(phrases: list[str]) -> str:
    return phrases[0] if len(phrases) == 1 else f"{', '.join(phrases[:-1])}, and {phrases[-1]}"


def phone_platform_hint(manifest: ProfileManifest | None = None) -> str:
    """The ``phone`` entry of ``PLATFORM_HINTS`` for ``manifest`` (default: the phone profile)."""
    manifest = manifest if manifest is not None else load_profile(PHONE_PROFILE, validate=False)
    lead = "You are running inside the Eternia app on the user's phone."
    absent = absent_capabilities(manifest)
    if not absent:
        return lead
    return (
        f"{lead} Here you have {_joined(absent)}. Do not suggest or plan work that needs them — "
        "including commands or scripts for the user to run. When a task needs any of these, say plainly "
        "that it needs the desktop (Hermes on the user's computer) and stop there."
    )


def install_phone_platform_hint() -> str:
    """Serve the phone hint under upstream's ``PLATFORM_HINTS["phone"]``; returns it.

    ``agent.system_prompt._default_platform_hint`` reads that table for a session whose platform
    is ``phone``. Called by the phone's entry before any request is served."""
    from agent.prompt_builder import PLATFORM_HINTS

    PLATFORM_HINTS["phone"] = hint = phone_platform_hint()
    return hint
