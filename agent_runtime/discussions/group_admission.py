"""Profile groups share the same atomic run admission and public room log."""
from __future__ import annotations

from .profile_groups import ProfileGroupSpec, group_initial, group_scope, profile_member
from .run_admission import Admission, admit
from .run_values import discussion_run_id

__layer__ = "stores"


def admit_group(store, spec: ProfileGroupSpec, *, key: str, actor: str, client: str, install_id: str):
    scope = group_scope(actor, client)
    run_id = discussion_run_id(scope, key)
    initial = group_initial(spec, actor, client)
    admission = Admission(initial, spec.participants, {p: i for i, p in enumerate(spec.participants)})
    return admit(store.connect, scope, key=key, topic="", actor_id=actor,
        identity=initial, load=lambda _: admission, allow_empty_topic=True,
        resolve=lambda ref, _: profile_member(run_id, ref, actor, client, install_id=install_id))
