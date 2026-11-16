"""Realm publishing — a realm puts a ready-made folder on the web (RT-REALM-PUBLISHING-PUSHES-A-FOLDER).

Slice S3 of Eternia ``docs/mission_control/planned/REALM_ARTIFACTS_REPOSITORY_2026-11-16.md``. A realm has a
second GitHub repository, its PUBLISHING repository (backend subject ``realm_publishing``), separate from the
working repository realm sync pushes to. This package pushes a folder the player or an agent already built, AS IT
IS, to that repository's Pages branch: no generator (owner Q1, 2026-11-16).

Named ``publishing`` and kept out of ``realm_sync/`` on purpose (review w1115e.27): ``realm_sync/artifacts.py``
calls a realm's synced working data "realm artifacts", and ``realm_sync/publish.py`` is realm sync's own push.
Nothing here reads or writes the sync clone; it reuses realm sync's git plumbing by import.

Entry point: :func:`publish_folder`, wired as ``runtime.realm.publishing.push`` (``serve_rpc.realm``) through
``realm_verbs.realm_publishing_push``.

=================  ======  =====================================================
module             layer   owns
=================  ======  =====================================================
push               lanes   ``publish_folder``: the refusals, the backend ask,
                           the publishing clone, the commit and the push
=================  ======  =====================================================
"""

from __future__ import annotations

from agent_runtime.realm_publishing.push import DEFAULT_BRANCH, publish_folder

__layer__ = "lanes"
__all__ = ["DEFAULT_BRANCH", "publish_folder"]
