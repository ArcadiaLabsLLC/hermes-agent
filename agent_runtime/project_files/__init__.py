"""Project files — hermes' direct reader of a project folder (path (b)).

Eternia plan ``docs/embedded_hermes/planned/PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md``
§6, row ``MC-PHONE-FILES-BOTH-LOCAL-READERS-FOLLOW-ONE-RULE-SPEC``: Eternia and hermes
both read a device's project folders directly, held to ONE rule spec owned by Eternia's
``packages/eternia_file_tree_spec/``. hermes gets that spec as a generated mirror
(``tests/fixtures/file_tree_spec/``, written by ``scripts/vendor_launcher_catalog.py
--file-tree-spec``) and runs every golden case on this reader
(``tests/agent_runtime/test_project_files_spec_cases.py``).

Entry points: ``reader.tree``, ``reader.read``, ``reader.grep``, the git verbs
``changes.status`` and ``changes.diff`` (row
``MC-PHONE-FILES-GIT-STATUS-AND-DIFF-ON-A-PHONE-PROJECT-FOLDER``, over the realm-sync git
port) and ``rules.ProjectFileRefusal``. Remote serving is added by
``MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE``, and the phone's
file tools bind here (``MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES``).
``media_handles.py`` stays the chat-media lane.

Modules, lowest layer first:

==========  =====================================================================
module      owns
==========  =====================================================================
rules       the spec's values and refusal codes (pinned to the mirror's rules.json)
paths       the root-relative path grammar
ignore      the walk's skip rules: .git, the skip list, the root .gitignore subset
replies     the pure halves of the verbs: binary probe, strict text, pages, grep lines
reader      the I/O: confinement, the walk, the three verbs
changes     status and diff on a git root, through realm_sync's git port
==========  =====================================================================
"""

__layer__ = "models"
