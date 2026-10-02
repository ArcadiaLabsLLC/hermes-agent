"""Discussion sessions reuse native workspace policy without moving their agents."""
from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
from agent_runtime.conversation_workspace import initialize_conversation_workspace
from agent_runtime.mission_chat_workdir import mission_chat_workdir_for_persona

__layer__ = "stores"


def initialize_member_workspace(db, member) -> None:
    persona = next((p for p in ensure_persisted_personas(load_agent_runtime_config())
                    if p.id == member["persona_id"]), None)
    initialize_conversation_workspace(db, member["session_id"],
        directory=mission_chat_workdir_for_persona(persona).path)
