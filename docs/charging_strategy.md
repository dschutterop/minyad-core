# Battery Charge/Discharge Strategy — superseded

This document described the v1/v2 battery strategy design (the reactive `HysteresisController`
FSM, the dormant `ChargeController`, and the rebuild prompt that produced `minyad/strategy/v2/`).

It has been superseded by a predictive LP-planner-based strategy that is not part of this
repository (Minyad Core ships the v1/v2 design only — see `minyad/strategy/v2/`). Consult git
history for this file's prior content if you need the v1/v2 design record.
