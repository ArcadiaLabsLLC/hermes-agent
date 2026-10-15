"""Work inspection and admission through Hermes's native task authority.

model: wire scope and refusals; native: public Kanban API adapter;
service: authorization and scope checks; rpc: authenticated method registration.
No scheduler, worker, task database or lifecycle writer lives here.
"""

__layer__ = "models"
