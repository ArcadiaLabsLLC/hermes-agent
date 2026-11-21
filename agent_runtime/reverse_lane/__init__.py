"""A computer drives a phone's engine over a lane the PHONE dials (D3 holds: no listener).

Plan: Eternia ``docs/embedded_hermes/planned/PHONE_DRIVEN_BY_A_COMPUTER_2026-11-21.md``
(T2, review w1118a.79, owner ruling 2026-11-21). Row:
``MC-PHONE-DRIVEN-THE-PHONE-DIALS-OUT-SO-A-COMPUTER-CAN-REACH-ITS-ENGINE``.

Modules, lowest layer first:

=======  ======  ==============================================================
module   layer   owns
=======  ======  ==============================================================
grants   stores  the phone's grants: level, verifier, the pairing they are bound to
lanes    lanes   ``ReverseLanes`` (park and splice; dial and admit), the hello hook
dialer   lanes   ``ReverseDialer``: one granted computer's dial loop
=======  ======  ==============================================================

What the computer's caller may do on the phone is ``call_authorization``'s computer arm:
an allowlist per grant level, never a device tier.
"""
