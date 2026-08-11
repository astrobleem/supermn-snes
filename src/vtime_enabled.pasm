; VTIME=1 assembly wrapper.  Keep diagnostic fixes out of dormant production
; bank bytes so an ordinary build retains its accepted exact ROM identity.
VTIME_DBCC_REGISTER_STRIDE_FIX=1
VTIME_IRQ_ENTRY_ACCOUNTING_FIX=1
VTIME_INPUT_DELAYED_COMMIT_FIX=1
.include "src/vtime.pasm"
