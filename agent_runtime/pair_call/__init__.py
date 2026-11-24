"""Any two of your devices keep ONE call between their engines, opened by whichever reaches the other first.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST`` (owner
2026-11-23: "whatever can open it should open it" / "both devices should try" / "in regards to using
ones connection i meant the call" / "they should both be able to confirm that requests are applied";
2026-11-24: "1 yes not confirmed"). Both engines dial; the first call to connect carries both
directions as LANES, one per caller, each with its own hello; a second call is closed by a rule both
sides compute the same way; every frame names its receiver, checked machine first.

Modules, lowest layer first:

==========  ======  ==========================================================
module      layer   owns
==========  ======  ==========================================================
envelope    models  a frame's receiver address and its machine-first check
call        lanes   ``PairCall``: one socket, its lanes, answers matched by lane and id
registry    stores  ``CallRegistry``: one call per far install, the dedupe rule
dialer      lanes   ``CallDialer``: one far install's redial loop
calls       lanes   ``PairCalls``: the serve's dial, accept, attach, lane admit and check
==========  ======  ==========================================================
"""

__layer__ = "models"
