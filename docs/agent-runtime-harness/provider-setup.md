# Client-neutral provider setup

Launcher Mission Control and Intelligence consume the same typed provider
service. Intelligence is the AI umbrella; Chat is one client. Neither surface
owns a provider catalog, credentials, OAuth engine or a second runtime manager.

`provider_catalog.provider_login_catalog()` reports `browser_login` and
`browser_login_methods`. `auth login <provider> --json --flow browser|device_code`
emits code/pending followed by exactly one confirmed done or error, naming the
resolved home. No token payload or raw helper error enters this stream.

Codex's existing PKCE loopback and device-code implementations are supported.
Nous, xAI and MiniMax use their canonical device flows; Nous guest upgrade keeps
its canonical promotion and settlement. Other providers honestly refuse this
transport. External credential ownership is unchanged.

The owned process is cancellable by its caller. Fresh grants persist only in
the selected auth store, without selecting an inference provider/model or
overwriting an external application's store. Launcher binds setup auth home to
the explicitly selected profile and refuses unavailable installation changes.
`auth set-key --stdin` continues to use the existing credential lifecycle.

Qualification: see `EterniaLauncher/docs/companion/planned/PROVIDER_HOME_SLICE_2026-09-25.md`.
