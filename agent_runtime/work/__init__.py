"""Work on the workspace todo boards, over the console RPC lane.

model: wire scope and refusals; store: the board and writer adapters; service: authorization and
scope checks; rpc: registration. No scheduler, worker or task database lives here.
"""

__layer__ = "models"
